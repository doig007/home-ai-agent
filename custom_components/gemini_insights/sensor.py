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
from .preprocessor import preprocess_sensor_data # Import data preprocessor
from homeassistant.components.recorder.history import get_significant_states # Import from recorder.history
from homeassistant.util import dt as dt_util # For timezone aware datetime objects

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    # Access merged config and options from hass.data, prepared by __init__.py
    # This ensures that options are immediately available and used after changes.
    domain_data = hass.data[DOMAIN][entry.entry_id]
    config = domain_data["config"] # Initial setup data
    options = domain_data["options"] # Runtime options, takes precedence

    api_key = config.get(CONF_API_KEY) 

    if not api_key:
        _LOGGER.error("Gemini API key not found in configuration. Component will not be set up.")
        # Consider raising ConfigEntryNotReady if you want Home Assistant to retry setup
        # from homeassistant.exceptions import ConfigEntryNotReady
        # raise ConfigEntryNotReady("API Key not available")
        return

    try:
        gemini_client = GeminiClient(api_key=api_key)
    except ValueError as e:
        _LOGGER.error(f"Failed to initialize Gemini Client: {e}")
        # This typically means an invalid API key was passed to the client's constructor.
        # Depending on HASS version, raising ConfigEntryAuthFailed might be appropriate
        # from homeassistant.exceptions import ConfigEntryAuthFailed
        # raise ConfigEntryAuthFailed("Invalid API Key for Gemini Client")
        return # Stop setup if client can't be initialized

    # Use options first, then config (for initial setup before options are saved), then default.
    update_interval_seconds = options.get(CONF_UPDATE_INTERVAL, config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))

    async def async_update_data():
        """Fetch data from Home Assistant, send to Gemini, and return insights."""
        _LOGGER.debug("Coordinator update called")
        
        # Prioritize options, then config, then empty list/default prompt
        entity_ids = options.get(CONF_ENTITIES, config.get(CONF_ENTITIES, []))
        prompt_template = options.get(CONF_PROMPT, config.get(CONF_PROMPT, DEFAULT_PROMPT))
        history_period_key = options.get(CONF_HISTORY_PERIOD, config.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD))

        if not entity_ids:
            _LOGGER.info("No entities configured for Gemini Insights. Skipping API call.")
            return {"insights": "No entities configured.", "alerts": "", "summary": ""}

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
                # Fetch historical data
                timedelta_params = HISTORY_PERIOD_TIMEDELTA_MAP.get(history_period_key)
                if timedelta_params:
                    start_time = now - timedelta(**timedelta_params)
                    _LOGGER.debug(f"Fetching history for {entity_id} from {start_time} to {now}")
                    
                    history_states_response = await hass.async_add_executor_job(
                        get_significant_states, # Use directly imported function
                        hass,
                        start_time,
                        None, # end_time (None means up to 'now')
                        [entity_id],
                        None, # filters
                        True, # include_start_time_state
                        False # minimal_response -> we want full state objects
                    )
                    
                    historical_states_data = []
                    if entity_id in history_states_response and history_states_response[entity_id]:
                        for s in history_states_response[entity_id]:
                            historical_states_data.append({
                                "state": s.state,
                                "attributes": dict(s.attributes),
                                "last_changed": s.last_changed.isoformat() if s.last_changed else None,
                                "last_updated": s.last_updated.isoformat() if s.last_updated else None,
                            })
                        _LOGGER.debug(f"Found {len(historical_states_data)} historical states for {entity_id}")
                    else:
                        _LOGGER.debug(f"No significant historical states found for {entity_id} in the period.")
                    
                    entity_data_map[entity_id] = {"historical_states": historical_states_data}
                    if not historical_states_data: # Also add current state if no history found to have some data
                        current_state_val = hass.states.get(entity_id)
                        if current_state_val:
                             entity_data_map[entity_id]["current_state"] = {
                                "state": current_state_val.state,
                                "attributes": dict(current_state_val.attributes),
                                "last_changed": current_state_val.last_changed.isoformat() if current_state_val.last_changed else None,
                                "last_updated": current_state_val.last_updated.isoformat() if current_state_val.last_updated else None,
                            }

                else:
                    _LOGGER.warning(f"Unknown history period key: {history_period_key} for entity {entity_id}. Defaulting to latest only.")
                    # Fallback to latest only for this entity if key is unknown (should not happen with config flow)
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

        # Construct raw data string for preprocessing
        raw_data_for_preprocessing_list = ["entity_id\tstate\tlast_changed"] # Header
        _LOGGER.debug(f"Entity data map before preprocessing: {entity_data_map}")

        for entity_id_key, entity_data_value in entity_data_map.items():
            # Current state handling
            if "current_state" in entity_data_value and entity_data_value["current_state"]:
                state_info = entity_data_value["current_state"]
                last_changed_iso = state_info.get("last_changed", dt_util.utcnow().isoformat())
                raw_data_for_preprocessing_list.append(
                    f"{entity_id_key}\t{state_info.get('state', 'unknown')}\t{last_changed_iso}"
                )
            
            # Historical states handling
            if "historical_states" in entity_data_value:
                for hist_state in entity_data_value["historical_states"]:
                    last_changed_iso = hist_state.get("last_changed", dt_util.utcnow().isoformat())
                    raw_data_for_preprocessing_list.append(
                        f"{entity_id_key}\t{hist_state.get('state', 'unknown')}\t{last_changed_iso}"
                    )

        entity_data_json = "{}" # Default to empty JSON
        if len(raw_data_for_preprocessing_list) > 1: # More than just header
            raw_data_string_for_gemini = "\n".join(raw_data_for_preprocessing_list)
            original_data_len = len(raw_data_string_for_gemini)
            _LOGGER.debug(f"Raw data for preprocessing (first 500 chars): {raw_data_string_for_gemini[:500]}")
            _LOGGER.debug(f"Original data length for preprocessing: {original_data_len} characters.")

            entity_data_json = preprocess_sensor_data(raw_data_string_for_gemini)
            processed_data_len = len(entity_data_json)
            _LOGGER.debug(f"Preprocessed data for Gemini (first 500 chars): {entity_data_json[:500]}")
            _LOGGER.debug(f"Processed data length: {processed_data_len} characters.")
            if original_data_len > 0:
                reduction_percentage = ((original_data_len - processed_data_len) / original_data_len) * 100
                _LOGGER.info(f"Preprocessing reduced data size by {reduction_percentage:.2f}% (from {original_data_len} to {processed_data_len} chars).")

        else:
            _LOGGER.info("No data to preprocess. Using empty JSON for Gemini.")
       
        
        if len(entity_data_json) > 100000: # Arbitrary limit, Gemini has token limits
            _LOGGER.warning(
                f"The data payload for Gemini is very large ({len(entity_data_json)} bytes) even after preprocessing. "
                "This might lead to API errors, high costs, or truncated analysis. "
                "Consider selecting fewer entities or a shorter history period."
            )

        try:
            # The GeminiClient's get_insights method is synchronous (def, not async def).
            # The DataUpdateCoordinator will run this in an executor thread.
            insights = await hass.async_add_executor_job(
                gemini_client.get_insights, prompt_template, entity_data_json
            )
            if insights  and "raw_text" in insights:
                _LOGGER.debug(f"Received insights from Gemini: {insights}")
                # Send notification with the raw response text
                await hass.services.async_call(
                    "notify",
                    "mobile_app_pixel_6_pro",
                    {"message": insights["raw_text"]},
                    blocking=False,  # False because we don't need to wait for the notification to send
                )
                return insights
            elif insights: # Partial success, but raw_text is missing
                _LOGGER.warning(f"Received insights from Gemini but raw_text is missing: {insights}")
                # Fallback if raw_text isn't in the response for some reason
                return {**insights, "raw_text": "Raw text not available."}
            else:
                _LOGGER.error("Failed to get insights from Gemini.")
                return {"insights": "Error fetching insights", "alerts": "Error", "summary": "Error", "raw_text": "Error fetching insights"}
        except Exception as e:
            _LOGGER.error(f"Exception during Gemini API call in coordinator: {e}")
            return {"insights": f"Exception: {e}", "alerts": "Exception", "summary": "Exception", "raw_text": f"Exception: {e}"}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="gemini_insights_sensor",
        update_method=async_update_data,
        update_interval=timedelta(seconds=update_interval_seconds),
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()

    # Create sensor entities
    sensors = [
        GeminiInsightsSensor(coordinator, "Insights"),
        GeminiInsightsSensor(coordinator, "Alerts"),
        GeminiInsightsSensor(coordinator, "Summary"),
        GeminiRawTextSensor(coordinator),
    ]
    async_add_entities(sensors)

class GeminiRawTextSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Gemini Insights Raw Text Sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Gemini Raw Response"
        # Unique ID should be based on the config entry and a unique identifier for this sensor
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_raw_text"
        self._attr_icon = "mdi:text-box-outline" # Icon for raw text

    @property
    def native_value(self):
        """Return the state of the sensor (the raw text)."""
        if self.coordinator.data is None:
            return "Initializing..."
        
        if hasattr(self.coordinator.data, 'get') and callable(self.coordinator.data.get):
            return self.coordinator.data.get("raw_text", "Raw text not available")
        else:
            _LOGGER.warning(
                f"Coordinator data for sensor {self.name} is not a dictionary (type: {type(self.coordinator.data)}). "
                f"Current coordinator data (snippet): {str(self.coordinator.data)[:200]}"
            )
            return "Error: Invalid data structure"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = {}
        attrs["last_update_status"] = "Success" if self.coordinator.last_update_success else "Failed"
        # The raw_text can be very long, so it's better to keep it as the main state
        # and not duplicate it in attributes unless a snippet is desired.
        # For now, no extra attributes beyond the standard ones.
        return attrs

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
        self._attr_name = f"Gemini {insight_type}"
        # Unique ID should be based on the config entry and the insight type
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain" # Generic icon, can be changed

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            # This can happen before the first successful update or if an update fails and returns None
            _LOGGER.debug(f"Coordinator data is None for {self.name}, returning Initializing...")
            return "Initializing..." 
        
        # Check if coordinator.data has a 'get' method (is dict-like)
        if hasattr(self.coordinator.data, 'get') and callable(self.coordinator.data.get):
            return self.coordinator.data.get(self._insight_type, "Not available")
        else:
            # This is the problematic case where data is not a dict (e.g., a coroutine or other unexpected type)
            _LOGGER.warning(
                f"Coordinator data for sensor {self.name} is not a dictionary (type: {type(self.coordinator.data)}). "
                f"This might indicate an issue with the DataUpdateCoordinator or the update_method. "
                f"Current coordinator data (snippet): {str(self.coordinator.data)[:200]}" 
            )
            return "Error: Invalid data" # Or some other error indicator for the sensor state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = {}
        # Add raw_data if the last update was successful and data is available and is a dictionary
        if self.coordinator.last_update_success and \
           self.coordinator.data and \
           isinstance(self.coordinator.data, dict):
            attrs["raw_data"] = self.coordinator.data
        
        # Add the status of the last update attempt
        attrs["last_update_status"] = "Success" if self.coordinator.last_update_success else "Failed"
        
        # The entity's own 'last_updated' attribute will reflect when HA last wrote its state.
        # If a more specific timestamp from the data source is needed, it should be extracted
        # from self.coordinator.data if available.
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
