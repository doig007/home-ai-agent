"""Sensor platform for Gemini Insights."""

from __future__ import annotations

import functools
import json
import logging
import pathlib
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTION_CONFIDENCE_THRESHOLD,
    CONF_AUTO_EXECUTE_ACTIONS,
    CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
    CONF_ENABLE_LEARNING,
    CONF_ENTITIES,
    CONF_FORECAST_HOURS,
    CONF_HISTORY_PERIOD,
    CONF_MAX_CONFIRMATION_REQUESTS,
    CONF_NOTIFICATION_SERVICE,
    CONF_PROMPT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_CONFIRMATION_NOTIFICATIONS,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_FORECAST_HOURS,
    DEFAULT_HISTORY_PERIOD,
    DEFAULT_MAX_CONFIRMATION_REQUESTS,
    DEFAULT_NOTIFICATION_SERVICE,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    HISTORY_LATEST_ONLY,
    HISTORY_PERIOD_TIMEDELTA_MAP,
)
from .learning import build_confirmation_actions
from .preprocessor import Preprocessor

_LOGGER = logging.getLogger(__name__)


class _SafePromptDict(dict):
    """Mapping that preserves unknown placeholders in custom prompts."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the sensor platform."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    gemini_client = entry_data.get("client")
    learning_manager = entry_data.get("learning_manager")
    if gemini_client is None or learning_manager is None:
        raise ConfigEntryNotReady("Gemini Insights entry data is not initialized")

    config = entry.data
    options = entry.options
    update_interval_seconds = options.get(
        CONF_UPDATE_INTERVAL,
        config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )

    async def async_update_data():
        """Fetch data from Home Assistant, send to Gemini, and return insights."""
        _LOGGER.debug("Coordinator update called")

        entity_ids = options.get(CONF_ENTITIES, [])
        prompt_template = options.get(CONF_PROMPT, DEFAULT_PROMPT)
        history_period_key = options.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD)
        auto_execute = options.get(CONF_AUTO_EXECUTE_ACTIONS, False)
        confidence_threshold = options.get(CONF_ACTION_CONFIDENCE_THRESHOLD, 0.7)
        enable_learning = options.get(CONF_ENABLE_LEARNING, DEFAULT_ENABLE_LEARNING)
        enable_confirmation_notifications = options.get(
            CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
            DEFAULT_ENABLE_CONFIRMATION_NOTIFICATIONS,
        )
        notification_service = options.get(
            CONF_NOTIFICATION_SERVICE,
            DEFAULT_NOTIFICATION_SERVICE,
        )
        forecast_hours = int(options.get(CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS))
        max_confirmation_requests = int(
            options.get(CONF_MAX_CONFIRMATION_REQUESTS, DEFAULT_MAX_CONFIRMATION_REQUESTS)
        )

        if not entity_ids:
            _LOGGER.info("No entities configured for Gemini Insights. Skipping API call.")
            return {
                "insights": "No entities configured.",
                "alerts": "",
                "forecast": "",
                "to_execute": [],
                "learning_updates": [],
                "confirmation_requests": [],
                "learning_profile": await learning_manager.async_get_prompt_payload(),
                "raw_text": "No entities configured.",
            }

        preprocessor = Preprocessor(hass, entity_ids)
        now = dt_util.utcnow()
        latest_states = await preprocessor.async_get_latest_states()
        entity_context = await preprocessor.async_get_entity_context()
        behavior_summary: dict[str, Any] = {
            "note": (
                "Only latest states were included. Use recorder history to let Gemini "
                "learn routines and produce stronger forecasts."
            ),
            "entities": {
                entity_id: {
                    "current_state": payload.get("s"),
                    "last_changed": payload.get("lc"),
                    "change_count": 0,
                }
                for entity_id, payload in latest_states.items()
            },
        }
        entity_payload: dict[str, Any] = latest_states

        if history_period_key != HISTORY_LATEST_ONLY:
            timedelta_params = HISTORY_PERIOD_TIMEDELTA_MAP.get(history_period_key)
            if timedelta_params:
                start_time_history = now - timedelta(**timedelta_params)
                get_history_job = functools.partial(
                    get_significant_states,
                    hass,
                    start_time_history,
                    None,
                    entity_ids,
                    include_start_time_state=True,
                    minimal_response=True,
                )
                history_states_response = await get_instance(hass).async_add_executor_job(
                    get_history_job
                )
                recent_events = await preprocessor.async_get_compact_recent_events(
                    history_states_response
                )
                behavior_summary = await preprocessor.async_get_behavior_summary(
                    history_states_response,
                    start_time_history,
                    now,
                )

                start_time_stats = max(now - timedelta(days=1), start_time_history)
                numeric_entity_ids = [
                    entity_id
                    for entity_id in entity_ids
                    if preprocessor._is_numeric_entity(entity_id)
                ]
                stats_response = await get_instance(hass).async_add_executor_job(
                    statistics_during_period,
                    hass,
                    start_time_stats,
                    None,
                    numeric_entity_ids,
                    "5minute",
                    None,
                    {"mean"},
                )
                long_term_stats = await preprocessor.async_get_compact_long_term_stats(
                    stats_response,
                    start_time_stats,
                )
                entity_payload = {
                    "latest_states": latest_states,
                    "recent_events": recent_events,
                    "long_term_stats": long_term_stats,
                }

        learning_profile = (
            await learning_manager.async_get_prompt_payload()
            if enable_learning
            else {
                "patterns": [],
                "recent_confirmations": [],
                "pending_confirmations": [],
                "last_forecast": None,
                "enabled": False,
            }
        )

        action_schema_json = await preprocessor.async_get_action_schema()
        final_prompt = prompt_template.format_map(
            _SafePromptDict(
                entity_data=json.dumps(entity_payload),
                entity_context=json.dumps(entity_context),
                behavior_summary=json.dumps(behavior_summary),
                household_learning=json.dumps(
                    {
                        "enabled": enable_learning,
                        "patterns": learning_profile.get("patterns", []),
                        "pending_confirmations": learning_profile.get(
                            "pending_confirmations",
                            [],
                        ),
                        "last_forecast": learning_profile.get("last_forecast"),
                    }
                ),
                confirmation_history=json.dumps(
                    learning_profile.get("recent_confirmations", [])
                ),
                forecast_hours=forecast_hours,
                action_schema=action_schema_json,
            )
        )

        prompt_size = len(final_prompt.encode("utf-8"))
        if prompt_size > 30000:
            _LOGGER.warning(
                "The final prompt for Gemini is very large (%s bytes). "
                "This may lead to errors or high costs. "
                "Consider reducing entities or history period.",
                prompt_size,
            )

        try:
            debug_dir = pathlib.Path(__file__).with_suffix("").parent / "debug_prompts"
            debug_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            await hass.async_add_executor_job(
                functools.partial(
                    (debug_dir / f"prompt_{ts}.txt").write_text,
                    final_prompt,
                    "utf-8",
                )
            )

            insights = await gemini_client.get_insights(final_prompt)
            if insights:
                _LOGGER.debug("Received insights from Gemini: %s", insights.get("insights"))

                if enable_learning:
                    await learning_manager.async_merge_learning_updates(
                        insights.get("learning_updates")
                    )
                    await learning_manager.async_store_forecast(
                        insights.get("forecast"),
                        forecast_hours,
                    )
                    queued_confirmations = await learning_manager.async_queue_confirmation_requests(
                        insights.get("confirmation_requests"),
                        latest_states,
                        max_confirmation_requests,
                    )
                else:
                    queued_confirmations = []

                if auto_execute:
                    to_execute = insights.get("to_execute") or []
                    for call in to_execute:
                        try:
                            confidence = float(call.get("confidence", 0))
                            if confidence < confidence_threshold:
                                _LOGGER.debug(
                                    "Skipping action due to low confidence (%s < %s): %s",
                                    confidence,
                                    confidence_threshold,
                                    call,
                                )
                                continue

                            domain = call.get("domain")
                            service = call.get("service")
                            service_data = json.loads(call.get("service_data"))
                            if not all(isinstance(value, str) for value in (domain, service)):
                                _LOGGER.warning(
                                    "Skipping malformed action (missing domain/service): %s",
                                    call,
                                )
                                continue

                            await hass.services.async_call(
                                domain,
                                service,
                                service_data,
                                blocking=False,
                            )
                            _LOGGER.debug("Executed Gemini-requested action: %s", call)
                        except Exception as err:
                            _LOGGER.error("Failed to execute action %s - %s", call, err)

                if (
                    enable_confirmation_notifications
                    and notification_service
                    and queued_confirmations
                ):
                    await _async_send_confirmation_notifications(
                        hass,
                        entry.entry_id,
                        notification_service,
                        queued_confirmations,
                    )

                refreshed_learning = (
                    await learning_manager.async_get_prompt_payload()
                    if enable_learning
                    else learning_profile
                )
                insights["learning_profile"] = refreshed_learning
                insights["pending_confirmations"] = refreshed_learning.get(
                    "pending_confirmations",
                    [],
                )
                return insights
            _LOGGER.error("Failed to get insights from Gemini.")
            return {
                "insights": "Error",
                "alerts": "Error",
                "forecast": "Error",
                "to_execute": [],
                "learning_updates": [],
                "confirmation_requests": [],
                "learning_profile": learning_profile,
                "raw_text": "Failed to get insights",
            }
        except Exception as err:
            _LOGGER.error("Exception during Gemini API call in coordinator: %s", err)
            return {
                "insights": f"Exception: {err}",
                "alerts": "Exception",
                "forecast": "Exception",
                "to_execute": [],
                "learning_updates": [],
                "confirmation_requests": [],
                "learning_profile": learning_profile,
                "raw_text": f"Exception: {err}",
            }

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="gemini_insights_sensor",
        update_method=async_update_data,
        update_interval=timedelta(seconds=update_interval_seconds),
    )
    coordinator.config_entry = entry

    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

    sensors = [
        GeminiInsightsSensor(coordinator, "Insights"),
        GeminiInsightsSensor(coordinator, "Alerts"),
        GeminiInsightsSensor(coordinator, "Forecast"),
        GeminiInsightsSensor(coordinator, "To Execute"),
        GeminiRawTextSensor(coordinator),
    ]
    async_add_entities(sensors)


async def _async_send_confirmation_notifications(
    hass: HomeAssistant,
    entry_id: str,
    notify_service: str,
    confirmation_requests: list[dict[str, Any]],
) -> None:
    """Send Home Assistant notifications asking the user to confirm a pattern."""
    if "." not in notify_service:
        _LOGGER.warning(
            "Notification service '%s' is invalid. Expected domain.service",
            notify_service,
        )
        return

    domain, service = notify_service.split(".", 1)
    for request in confirmation_requests:
        message = request["question"]
        if request.get("reason"):
            message = f"{message}\nWhy: {request['reason']}"

        await hass.services.async_call(
            domain,
            service,
            {
                "title": "Gemini Insights learning check",
                "message": message,
                "data": {
                    "tag": f"{DOMAIN}_{entry_id}_{request['tag']}",
                    "group": DOMAIN,
                    "actions": build_confirmation_actions(entry_id, request["tag"]),
                },
            },
            blocking=False,
        )


class GeminiRawTextSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Gemini Insights Raw Text Sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Gemini Raw Response"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_raw_text"
        self._attr_icon = "mdi:text-box-outline"

    @property
    def native_value(self):
        """Return a short identifier instead of the full text."""
        if not isinstance(self.coordinator.data, dict):
            return "Error"
        raw = self.coordinator.data.get("raw_text", "")
        # first 50 chars + SHA-1 hash (always < 255)
        return raw[:50] + "…" if len(raw) > 50 else raw

    @property
    def extra_state_attributes(self):
        """Full raw text in attributes (no length limit)."""
        if not isinstance(self.coordinator.data, dict):
            return {}
        return {"raw_text": self.coordinator.data.get("raw_text")}

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower().replace(" ", "_")
        self._attr_name = f"Gemini {insight_type}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """Return a concise state under Home Assistant's state length limit."""
        if self.coordinator.data is None:
            return "Initializing..."

        if not isinstance(self.coordinator.data, dict):
            _LOGGER.warning(
                "Coordinator data is not a dictionary: %s",
                type(self.coordinator.data),
            )
            return "Error: Invalid data"

        value = self.coordinator.data.get(self._insight_type)
        if value in (None, "", []):
            return "Not available"

        if isinstance(value, str):
            return f"Updated ({len(value)} chars)"
        if isinstance(value, list):
            return f"Updated ({len(value)} items)"
        if isinstance(value, dict):
            return f"Updated ({len(value)} fields)"

        return str(value)[:255]

    @property
    def extra_state_attributes(self):
        """Return the state attributes, including the full payload."""
        attrs = {
            "last_update_status": (
                "Success" if self.coordinator.last_update_success else "Failed"
            )
        }

        if isinstance(self.coordinator.data, dict):
            attrs[self._insight_type] = self.coordinator.data.get(
                self._insight_type,
                "Not available",
            )
            attrs["learning_profile"] = self.coordinator.data.get("learning_profile")
            attrs["pending_confirmations"] = self.coordinator.data.get(
                "pending_confirmations",
                [],
            )

        return attrs

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower().replace(" ", "_")
        self._attr_name = f"Gemini {insight_type}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """Return a concise state under Home Assistant's state length limit."""
        if self.coordinator.data is None:
            return "Initializing..."

        if not isinstance(self.coordinator.data, dict):
            _LOGGER.warning(
                "Coordinator data is not a dictionary: %s",
                type(self.coordinator.data),
            )
            return "Error: Invalid data"

        value = self.coordinator.data.get(self._insight_type)
        if value in (None, "", []):
            return "Not available"

        if isinstance(value, str):
            return f"Updated ({len(value)} chars)"
        if isinstance(value, list):
            return f"Updated ({len(value)} items)"
        if isinstance(value, dict):
            return f"Updated ({len(value)} fields)"

        return str(value)[:255]

    @property
    def extra_state_attributes(self):
        """Return the state attributes, including the full payload."""
        attrs = {
            "last_update_status": (
                "Success" if self.coordinator.last_update_success else "Failed"
            )
        }

        if isinstance(self.coordinator.data, dict):
            attrs[self._insight_type] = self.coordinator.data.get(
                self._insight_type,
                "Not available",
            )
            attrs["learning_profile"] = self.coordinator.data.get("learning_profile")
            attrs["pending_confirmations"] = self.coordinator.data.get(
                "pending_confirmations",
                [],
            )

        return attrs

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower().replace(" ", "_")
        self._attr_name = f"Gemini {insight_type}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """Return a concise state under Home Assistant's state length limit."""
        if self.coordinator.data is None:
            return "Initializing..."

        if not isinstance(self.coordinator.data, dict):
            _LOGGER.warning(
                "Coordinator data is not a dictionary: %s",
                type(self.coordinator.data),
            )
            return "Error: Invalid data"

        value = self.coordinator.data.get(self._insight_type)
        if value in (None, "", []):
            return "Not available"

        if isinstance(value, str):
            return f"Updated ({len(value)} chars)"
        if isinstance(value, list):
            return f"Updated ({len(value)} items)"
        if isinstance(value, dict):
            return f"Updated ({len(value)} fields)"

        return str(value)[:255]

    @property
    def extra_state_attributes(self):
        """Return the state attributes, including the full payload."""
        attrs = {
            "last_update_status": (
                "Success" if self.coordinator.last_update_success else "Failed"
            )
        }

        if isinstance(self.coordinator.data, dict):
            attrs[self._insight_type] = self.coordinator.data.get(
                self._insight_type,
                "Not available",
            )
            attrs["learning_profile"] = self.coordinator.data.get("learning_profile")
            attrs["pending_confirmations"] = self.coordinator.data.get(
                "pending_confirmations",
                [],
            )

        return attrs

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower().replace(" ", "_")
        self._attr_name = f"Gemini {insight_type}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """Return a concise state under Home Assistant's state length limit."""
        if self.coordinator.data is None:
            return "Initializing..."

        if not isinstance(self.coordinator.data, dict):
            _LOGGER.warning(
                "Coordinator data is not a dictionary: %s",
                type(self.coordinator.data),
            )
            return "Error: Invalid data"

        value = self.coordinator.data.get(self._insight_type)
        if value in (None, "", []):
            return "Not available"

        if isinstance(value, str):
            return f"Updated ({len(value)} chars)"
        if isinstance(value, list):
            return f"Updated ({len(value)} items)"
        if isinstance(value, dict):
            return f"Updated ({len(value)} fields)"

        return str(value)[:255]

    @property
    def extra_state_attributes(self):
        """Return the state attributes, including the full payload."""
        attrs = {
            "last_update_status": (
                "Success" if self.coordinator.last_update_success else "Failed"
            )
        }

        if isinstance(self.coordinator.data, dict):
            attrs[self._insight_type] = self.coordinator.data.get(
                self._insight_type,
                "Not available",
            )
            attrs["learning_profile"] = self.coordinator.data.get("learning_profile")
            attrs["pending_confirmations"] = self.coordinator.data.get(
                "pending_confirmations",
                [],
            )

        return attrs

    @property
    def native_value(self):
        """Return a short identifier instead of the full text."""
        if not isinstance(self.coordinator.data, dict):
            return "Error"
        raw = self.coordinator.data.get("raw_text", "")
        return raw[:50] + "..." if len(raw) > 50 else raw or "No response"

    @property
    def extra_state_attributes(self):
        """Full raw text plus learning context in attributes."""
        if not isinstance(self.coordinator.data, dict):
            return {}
        return {
            "raw_text": self.coordinator.data.get("raw_text"),
            "learning_profile": self.coordinator.data.get("learning_profile"),
            "pending_confirmations": self.coordinator.data.get(
                "pending_confirmations",
                [],
            ),
        }

    def __init__(self, coordinator: DataUpdateCoordinator):
        """Initialize the raw response sensor."""
        super().__init__(coordinator)
        self._attr_name = "Gemini Raw Response"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_raw_text"
        self._attr_icon = "mdi:text-box-outline"

    @property
    def native_value(self):
        """Return a short identifier instead of the full text."""
        if not isinstance(self.coordinator.data, dict):
            return "Error"
        raw = self.coordinator.data.get("raw_text", "")
        return raw[:50] + "..." if len(raw) > 50 else raw or "No response"

    @property
    def extra_state_attributes(self):
        """Full raw text plus learning context in attributes."""
        if not isinstance(self.coordinator.data, dict):
            return {}
        return {
            "raw_text": self.coordinator.data.get("raw_text"),
            "learning_profile": self.coordinator.data.get("learning_profile"),
            "pending_confirmations": self.coordinator.data.get(
                "pending_confirmations",
                [],
            ),
        }


class GeminiInsightsSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Gemini Insights Sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower()
        self._attr_name = f"Gemini {insight_type.capitalize()}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """
        Return a short, concise state that is always under 255 characters.
        The full text will be moved to the attributes.
        """
        if self.coordinator.data is None:
            return "Initializing..."
        
        if not isinstance(self.coordinator.data, dict):
            _LOGGER.warning(f"Coordinator data is not a dictionary: {type(self.coordinator.data)}")
            return "Error: Invalid data"

        full_text = self.coordinator.data.get(self._insight_type, "")
        if not full_text:
            return "Not available"

        # Return a short state with the character count. This is always < 255 chars.
        return f"Updated ({len(full_text)} chars)"

    @property
    def extra_state_attributes(self):
        """Return the state attributes, including the full insight text."""
        attrs = {
            "last_update_status": "Success" if self.coordinator.last_update_success else "Failed"
        }
        
        if isinstance(self.coordinator.data, dict):
            # Add the full, long-form text as an attribute.
            # The key will be 'insights', 'alerts', or 'to_execute'.
            attrs[self._insight_type] = self.coordinator.data.get(self._insight_type, "Not available")

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower().replace(" ", "_")
        self._attr_name = f"Gemini {insight_type}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain"

    @property
    def native_value(self):
        """Return a concise state under Home Assistant's state length limit."""
        if self.coordinator.data is None:
            return "Initializing..."

        if not isinstance(self.coordinator.data, dict):
            _LOGGER.warning(
                "Coordinator data is not a dictionary: %s",
                type(self.coordinator.data),
            )
            return "Error: Invalid data"

        value = self.coordinator.data.get(self._insight_type)
        if value in (None, "", []):
            return "Not available"

        if isinstance(value, str):
            return f"Updated ({len(value)} chars)"
        if isinstance(value, list):
            return f"Updated ({len(value)} items)"
        if isinstance(value, dict):
            return f"Updated ({len(value)} fields)"

        return str(value)[:255]

    @property
    def extra_state_attributes(self):
        """Return the state attributes, including the full payload."""
        attrs = {
            "last_update_status": (
                "Success" if self.coordinator.last_update_success else "Failed"
            )
        }

        if isinstance(self.coordinator.data, dict):
            attrs[self._insight_type] = self.coordinator.data.get(
                self._insight_type,
                "Not available",
            )
            attrs["learning_profile"] = self.coordinator.data.get("learning_profile")
            attrs["pending_confirmations"] = self.coordinator.data.get(
                "pending_confirmations",
                [],
            )

        return attrs
