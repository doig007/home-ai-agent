"""Sensor platform for Gemini Insights."""
import logging
import json
from datetime import timedelta, datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_ENTITIES,
    CONF_PROMPT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    CONF_API_KEY,
    CONF_HISTORY_PERIOD,
    DEFAULT_HISTORY_PERIOD,
    HISTORY_LATEST_ONLY,
    HISTORY_PERIOD_TIMEDELTA_MAP,
    CONF_AUTO_EXECUTE_ACTIONS,
    CONF_ACTION_CONFIDENCE_THRESHOLD,
)
from .gemini_client import GeminiClient
from .preprocessor import Preprocessor

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the sensor platform."""
    entry_obj = hass.data[DOMAIN][entry.entry_id]["entry"]
    api_key = entry_obj.data[CONF_API_KEY]

    if not api_key:
        _LOGGER.error("Gemini API key not found in configuration.")
        return

    # === SYNCHRONOUS CLIENT INITIALIZATION ===
    try:
        gemini_client = await GeminiClient.async_create(hass, api_key)
    except Exception as e:
        _LOGGER.error(f"Failed to initialize Gemini Client: {e}")
        # Raising ConfigEntryNotReady will cause Home Assistant to retry the setup later.
        raise ConfigEntryNotReady(f"Failed to initialize Gemini Client: {e}") from e

    # === COORDINATOR SETUP ===
    config  = entry.data
    options = entry.options
    update_interval_seconds = options.get(
        CONF_UPDATE_INTERVAL,
        config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    )

    async def async_update_data():
        """Fetch data from Home Assistant, send to Gemini, and return insights."""
        _LOGGER.debug("Coordinator update called")
        
        entity_ids = options.get(CONF_ENTITIES, [])
        prompt_template = options.get(CONF_PROMPT, DEFAULT_PROMPT)
        history_period_key = options.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD)
        auto_execute = options.get(CONF_AUTO_EXECUTE_ACTIONS, False)
        confidence_threshold = options.get(CONF_ACTION_CONFIDENCE_THRESHOLD, 0.7)

        if not entity_ids:
            _LOGGER.info("No entities configured for Gemini Insights. Skipping API call.")
            return {"insights": "No entities configured.", "alerts": "", "actions": "", "raw_text": "No entities configured."}

        # === START OF REFACTORED DATA FETCHING AND PROCESSING ===
        preprocessor = Preprocessor(hass, entity_ids)
        now = dt_util.utcnow()
        entity_data_json = "{}"

        # 1a. Fetch data based on user's history preference
        if history_period_key == HISTORY_LATEST_ONLY:
            entity_data_json = await preprocessor.async_get_compact_latest_states_json()
        else:
            # Fetch both historical states and long-term stats for other periods
            timedelta_params = HISTORY_PERIOD_TIMEDELTA_MAP.get(history_period_key)
            if timedelta_params:
                start_time_history = now - timedelta(**timedelta_params)
                
                # Fetch recent events (now returns compact data)
                history_states_response = await get_instance(hass).async_add_executor_job(
                    get_significant_states,
                    hass, start_time_history, None, entity_ids,
                    include_start_time_state=True, minimal_response=True # Use minimal_response
                )
                recent_events_json = await preprocessor.async_get_compact_recent_events_json(history_states_response)

                # Fetch long-term stats (only for numeric entities)
                start_time_stats = now - timedelta(days=1)
                numeric_entity_ids = [eid for eid in entity_ids if preprocessor._is_numeric_entity(eid)]
                stats_response = await get_instance(hass).async_add_executor_job(
                    statistics_during_period,
                    hass, start_time_stats, None, numeric_entity_ids, "5minute", None, {"mean"}
                )
                long_term_stats_json = await preprocessor.async_get_compact_long_term_stats_json(stats_response)

                # Combine them into a single JSON object string for the prompt
                combined_payload = {
                    "recent_events": json.loads(recent_events_json),
                    "long_term_stats": json.loads(long_term_stats_json)
                }
                entity_data_json = json.dumps(combined_payload)

        # 1b. Get the action schema from Home Assistant.
        action_schema_json = await preprocessor.async_get_action_schema()
        
        # 2. Build the final prompt
        final_prompt = prompt_template.format(
            entity_data=entity_data_json,
            action_schema=action_schema_json
        )
        

        prompt_size = len(final_prompt.encode('utf-8'))
        if prompt_size > 30000:
            _LOGGER.warning(
                "The final prompt for Gemini is very large (%s bytes). "
                "This may lead to errors or high costs. "
                "Consider reducing entities or history period.",
                prompt_size
            )

        try:
            import functools, pathlib, time
            debug_dir = pathlib.Path(__file__).with_suffix('').parent / "debug_prompts"
            debug_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            content = final_prompt
            
            # non-blocking write
            await hass.async_add_executor_job(
                functools.partial(
                    (debug_dir / f"prompt_{ts}.txt").write_text,
                    content,
                    "utf-8",
                )
            )

            # Call the simplified Gemini client with the complete prompt
            insights = await gemini_client.get_insights(final_prompt)
            
            if insights:
                _LOGGER.debug(f"Received insights from Gemini: {insights.get('insights')}")

                # Optionally execute any actions Gemini asked for
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

                            domain  = call.get("domain")
                            service = call.get("service")
                            service_data = json.loads(call.get("service_data"))
                            if not all(isinstance(x, str) for x in (domain, service)):
                                _LOGGER.warning("Skipping malformed action (missing domain/service): %s", call)
                                continue

                            await hass.services.async_call(domain, service, service_data, blocking=False) 
                            _LOGGER.debug("Executed Gemini-requested action: %s", call)
                        except Exception as e:
                            _LOGGER.error("Failed to execute action %s - %s", call, e)


                # Send a notification with the insights
                await hass.services.async_call(
                    "notify",
                    "mobile_app_pixel_6_pro",
                    {"message": insights.get("insights", "No raw text available.")},
                    blocking=False,
                )
                return insights
            else:
                _LOGGER.error("Failed to get insights from Gemini.")
                return {"insights": "Error", "alerts": "Error", "to_execute": [], "raw_text": "Failed to get insights"}
        except Exception as e:
            _LOGGER.error(f"Exception during Gemini API call in coordinator: {e}")
            return {"insights": f"Exception: {e}", "alerts": "Exception", "to_execute": [], "raw_text": f"Exception: {e}"}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="gemini_insights_sensor",
        update_method=async_update_data,
        update_interval=timedelta(seconds=update_interval_seconds),
    )

    await coordinator.async_config_entry_first_refresh()

    sensors = [
        GeminiInsightsSensor(coordinator, "Insights"),
        GeminiInsightsSensor(coordinator, "Alerts"),
        GeminiInsightsSensor(coordinator, "To Execute"),
        GeminiRawTextSensor(coordinator),
    ]
    async_add_entities(sensors)


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
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return "Initializing..."
        
        if isinstance(self.coordinator.data, dict):
            return self.coordinator.data.get(self._insight_type, "Not available")

        _LOGGER.warning(f"Coordinator data is not a dictionary: {type(self.coordinator.data)}")
        return "Error: Invalid data"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = {}
        attrs["last_update_status"] = "Success" if self.coordinator.last_update_success else "Failed"
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
