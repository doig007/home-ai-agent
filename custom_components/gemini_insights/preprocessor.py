"""Preprocessor for Home Assistant data to be sent to Gemini."""
import json
import logging
from datetime import datetime, timedelta
from homeassistant.core import HomeAssistant
from homeassistant.components.recorder import history
from homeassistant.helpers.json import JSONEncoder

_LOGGER = logging.getLogger(__name__)

class Preprocessor:
    """
    Handles fetching and preprocessing of Home Assistant data for the Gemini API.
    """

    def __init__(self, hass: HomeAssistant, entity_ids: list[str]):
        """
        Initializes the preprocessor.

        Args:
            hass: The Home Assistant instance.
            entity_ids: A list of entity IDs to fetch data for.
        """
        self.hass = hass
        self.entity_ids = entity_ids
        self.last_updated = None

    async def async_get_entity_data_json(self) -> str:
        """
        Fetches historical data for the specified entities and formats it as a JSON string.
        This function is designed to be robust and handle multiple entities correctly.
        On the first run, it fetches all historical data. On subsequent runs, it
        will only fetch data since the last update.

        Returns:
            A JSON string containing the historical data for all specified entities.
        """
        all_entity_data = {}
        
        # If last_updated is None, fetch all historical data. Otherwise, fetch
        # data since the last update.
        start_time = self.last_updated or datetime.utcnow() - timedelta(days=1)

        for entity_id in self.entity_ids:
            try:
                # Fetch history for each entity
                entity_history = await self.hass.async_add_executor_job(
                    history.get_significant_states,
                    self.hass,
                    start_time,
                    None,
                    [entity_id],
                    None,
                    True, # include_start_time_state
                    False # minimal_response
                )

                if entity_id not in entity_history:
                    _LOGGER.warning(f"No history found for entity: {entity_id}")
                    continue

                # Process the states into a more compact format
                processed_states = []
                for state in entity_history[entity_id]:
                    processed_states.append({
                        "s": state.state,
                        "t": state.last_changed.isoformat(),
                    })

                all_entity_data[entity_id] = {
                    "current_state": self.hass.states.get(entity_id).state if self.hass.states.get(entity_id) else "unknown",
                    "history": processed_states,
                }
                _LOGGER.debug(f"Successfully processed history for {entity_id}")

            except Exception as e:
                _LOGGER.error(f"Error fetching or processing history for entity {entity_id}: {e}")
        
        if not all_entity_data:
            _LOGGER.warning("No data could be fetched for any of the specified entities.")
            return json.dumps({})

        # Update the last_updated timestamp to the current time
        self.last_updated = datetime.utcnow()

        # Use Home Assistant's JSONEncoder to handle special data types
        return json.dumps(all_entity_data, cls=JSONEncoder, indent=2)
