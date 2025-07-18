"""Sensor platform for Gemini Insights."""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.exceptions import ConfigEntryNotReady

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
)
from .gemini_client import GeminiClient
from .preprocessor import Preprocessor
from homeassistant.components.recorder.history import get_significant_states # Import from recorder.history
from homeassistant.util import dt as dt_util # For timezone aware datetime objects

PLATFORMS = ["sensor"]  # local copy in sensor.py

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    domain_data = hass.data[DOMAIN][entry.entry_id]
    config = domain_data["config"]
    options = domain_data["options"]

    api_key = config.get(CONF_API_KEY) 

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

    # now safe to forward
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # store the client where the coordinator will pick it up later
    domain_data["gemini_client"] = gemini_client
    
    # === COORDINATOR SETUP ===
    update_interval_seconds = options.get(CONF_UPDATE_INTERVAL, config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))

    async def async_update_data():
        """Fetch data from Home Assistant, send to Gemini, and return insights."""
        _LOGGER.debug("Coordinator update called")
        
        entity_ids = options.get(CONF_ENTITIES, config.get(CONF_ENTITIES, []))
        prompt_template = options.get(CONF_PROMPT, config.get(CONF_PROMPT, DEFAULT_PROMPT))
        history_period_key = options.get(CONF_HISTORY_PERIOD, config.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD))

        if not entity_ids:
            _LOGGER.info("No entities configured for Gemini Insights. Skipping API call.")
            return {"insights": "No entities configured.", "alerts": "", "actions": "", "raw_text": "No entities configured."}

        entity_data_map = {}
        now = dt_util.utcnow()

        for entity_id in entity_ids:
            if history_period_key == HISTORY_LATEST_ONLY:
                state = hass.states.get(entity_id)
                if state:
                    entity_data_map[entity_id] = {
                        "current_state": {
                            "state": state.state,
                            "attributes": dict(state.attributes),
                            "last_changed": state.last_changed.isoformat() if state.last_changed else None,
                            "last_updated": state.last_updated.isoformat() if state.last_updated else None,
                        }
                    }
                else:
                    entity_data_map[entity_id] = {"current_state": None}
                    _LOGGER.warning(f"Entity {entity_id} not found for current state.")
            else:
                timedelta_params = HISTORY_PERIOD_TIMEDELTA_MAP.get(history_period_key)
                if timedelta_params:
                    start_time = now - timedelta(**timedelta_params)
                    history_states_response = await hass.async_add_executor_job(
                        get_significant_states,
                        hass, start_time, None, [entity_id],
                        None, True, False
                    )
                    
                    historical_states_data = []
                    if entity_id in history_states_response and history_states_response[entity_id]:
                        for s in history_states_response[entity_id]:
                            historical_states_data.append({
                                "state": s.state,
                                "attributes": dict(s.attributes),
                                "last_changed": s.last_changed.isoformat(),
                                "last_updated": s.last_updated.isoformat(),
                            })
                    entity_data_map[entity_id] = {"historical_states": historical_states_data}
                    if not historical_states_data:
                        current_state_val = hass.states.get(entity_id)
                        if current_state_val:
                             entity_data_map[entity_id]["current_state"] = {
                                "state": current_state_val.state,
                                "attributes": dict(current_state_val.attributes),
                                "last_changed": current_state_val.last_changed.isoformat(),
                                "last_updated": current_state_val.last_updated.isoformat(),
                            }
                else:
                    _LOGGER.warning(f"Unknown history period key: {history_period_key}. Falling back to latest.")
                    state = hass.states.get(entity_id)
                    if state:
                         entity_data_map[entity_id] = {
                            "current_state": { "state": state.state, "attributes": dict(state.attributes) }
                         }

        preprocessor = Preprocessor(hass, entity_ids)
        entity_data_json = await preprocessor.async_get_entity_data_json()

        # ------------------------------------------------------------------
        # Build the new prompt
        # ------------------------------------------------------------------
        preprocessor = Preprocessor(hass, entity_ids)
        entity_data_json = await preprocessor.async_get_entity_data_json()

        # New prompt template – can be overriden in options
        prompt_template = options.get(
            CONF_PROMPT,
            """
Home Assistant data for the family home.

Long-term averages (48 half-hour slots for last day):
{long_term_stats}

Recent raw events (last 6 h):
{recent_events}

Provide:
1. Concise insights based on observed trends.
2. Alerts if anything looks unusual.
3. Recommended actions.

Respond extremely briefly, suitable for a phone notification.
""",
        )

        # Get the action schema from Home Assistant and append to the prompt template
        action_schema = await preprocessor.async_get_action_schema()
        prompt_template += f"\nAvailable actions:\n{action_schema}\n"

        if len(entity_data_json) > 100000:
            _LOGGER.warning("The data payload for Gemini is very large (%s bytes).", len(entity_data_json))

        if len(entity_data_json) > 100000:
            _LOGGER.warning("The data payload for Gemini is very large (%s bytes).", len(entity_data_json))

        try:
            # DEBUG: write prompt + data to disk
            import os, pathlib, time
            debug_dir = pathlib.Path(__file__).with_suffix('').parent / "debug_prompts"
            debug_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            with open(debug_dir / f"prompt_{ts}.txt", "w", encoding="utf-8") as f:
                f.write("==========  PROMPT  ==========\n")
                f.write(prompt_template)
                f.write("\n\n==========  ENTITY DATA  ==========\n")
                f.write(entity_data_json)

            insights = await hass.async_add_executor_job(
                gemini_client.get_insights, prompt_template, entity_data_json
            )
            if insights:
                _LOGGER.debug(f"Received insights from Gemini: {insights.get('insights')}")

                # Optionally execute any actions Gemini asked for
                to_execute = insights.get("to_execute") or []
                for call in to_execute:
                    try:
                        await hass.services.async_call(
                            call["domain"],
                            call["service"],
                            call["service_data"],
                            blocking=False,
                        )
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
                return {"insights": "Error", "alerts": "Error", "actions": "Error", "raw_text": "Failed to get insights"}
        except Exception as e:
            _LOGGER.error(f"Exception during Gemini API call in coordinator: {e}")
            return {"insights": f"Exception: {e}", "alerts": "Exception", "actions": "Exception", "raw_text": f"Exception: {e}"}

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
        GeminiInsightsSensor(coordinator, "Actions"),
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
