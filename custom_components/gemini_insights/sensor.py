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
from homeassistant.components import history # For fetching history
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

                    # get_significant_states returns a dict entity_id: [states]
                    # We are calling it for one entity_id at a time.
                    history_states_response = await hass.async_add_executor_job(
                        history.get_significant_states,
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

        import json
        entity_data_json = json.dumps(entity_data_map, indent=2)

        if len(entity_data_json) > 100000: # Arbitrary limit, Gemini has token limits
            _LOGGER.warning(
                f"The data payload for Gemini is very large ({len(entity_data_json)} bytes). "
                "This might lead to API errors, high costs, or truncated analysis. "
                "Consider selecting fewer entities or a shorter history period."
            )

        try:
            # The GeminiClient's get_insights method is synchronous (def, not async def).
            # The DataUpdateCoordinator will run this in an executor thread.
            insights = await hass.async_add_executor_job(
                gemini_client.get_insights, prompt_template, entity_data_json
            )
            if insights:
                _LOGGER.debug(f"Received insights from Gemini: {insights}")
                return insights
            else:
                _LOGGER.error("Failed to get insights from Gemini.")
                return {"insights": "Error fetching insights", "alerts": "Error", "summary": "Error"}
        except Exception as e:
            _LOGGER.error(f"Exception during Gemini API call in coordinator: {e}")
            return {"insights": f"Exception: {e}", "alerts": "Exception", "summary": "Exception"}

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
    ]
    async_add_entities(sensors)


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
