import json
import logging
from datetime import timedelta
from statistics import mean
from typing import Any, Dict, List, Union

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.json import JSONEncoder
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import LazyState
from homeassistant.components.recorder.statistics import (
    statistics_during_period,
    StatisticData,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

class Preprocessor:
    """A class to format Home Assistant data into a compact JSON payload for Gemini."""

    def __init__(self, hass: HomeAssistant, entity_ids: List[str]):
        """Initialize the preprocessor."""
        self.hass = hass
        self.entity_ids = entity_ids

    def _is_numeric_entity(self, entity_id: str) -> bool:
        """Check if an entity's state is numeric."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        try:
            float(state.state)
            return True
        except (ValueError, TypeError):
            return False

    async def async_get_compact_long_term_stats_json(
        self, stats: Dict[str, List[StatisticData]]
    ) -> str:
        """Return a compact JSON string of 48 half-hour slots with per-entity averages."""
        if not stats:
            return "{}"

        # Group stats by entity
        entity_stats: Dict[str, Dict[int, List[float]]] = {
            eid: {i: [] for i in range(48)} for eid in self.entity_ids
        }
        
        start_of_day = list(stats.values())[0][0]["start"].replace(hour=0, minute=0, second=0, microsecond=0)

        for entity_id, stat_list in stats.items():
            if not self._is_numeric_entity(entity_id):
                continue  # Skip non-numeric entities entirely

            for row in stat_list:
                # Calculate slot index from the start of the 24h period
                slot = int((row["start"] - start_of_day).total_seconds() // 1800)
                if 0 <= slot < 48 and row.get("mean") is not None:
                    entity_stats[entity_id][slot].append(row["mean"])

        # Format into a compact structure, removing empty slots/entities
        compact_payload = {}
        for entity_id, slots in entity_stats.items():
            entity_payload = {
                slot: round(mean(values), 2)
                for slot, values in slots.items()
                if values
            }
            if entity_payload:
                compact_payload[entity_id] = entity_payload

        return await self.hass.async_add_executor_job(
            json.dumps, compact_payload, cls=JSONEncoder
        )

    async def async_get_compact_recent_events_json(
        self, history: Dict[str, List[State]]
    ) -> str:
        """Return a compact JSON string of recent state changes, omitting attributes."""
        if not history:
            return "{}"
            
        # Create a payload with only state and last_changed, which is far more compact.
        payload = {}
        for entity_id, states in history.items():
            if not states:
                continue
            
            compact_states = []
            for s in states:
                state_val = None
                timestamp_iso = None

                if isinstance(s, LazyState):
                    state_val = s.state
                    timestamp_iso = s.last_updated.isoformat()
                elif isinstance(s, dict):
                    state_val = s.get('s')
                    timestamp_iso = dt_util.utc_from_timestamp(s.get('lu', 0)).isoformat()

                if state_val is not None:
                    compact_states.append({"s": state_val, "t": timestamp_iso})

            payload[entity_id] = compact_states

        return await self.hass.async_add_executor_job(
            json.dumps, payload, cls=JSONEncoder
        )

    async def async_get_compact_latest_states_json(self) -> str:
        """Return a compact JSON string of the latest states, omitting attributes."""
        payload = {}
        for entity_id in self.entity_ids:
            state = self.hass.states.get(entity_id)
            if state:
                # Only include state and last_changed for compactness
                payload[entity_id] = {
                    "s": state.state,
                    "lc": state.last_changed.isoformat(),
                }
        return await self.hass.async_add_executor_job(
            json.dumps, payload, cls=JSONEncoder
        )
    
    async def async_get_action_schema(self) -> str:
        """Return a compact JSON list of allowed actions, minus a few dangerous ones."""
        from homeassistant.helpers import service
        import functools
        
        # Fetch service descriptions (async)
        services = await service.async_get_all_descriptions(self.hass)
        
        # Build the filtered list in the event loop (tiny, safe)
        actions = []
        for dom, srvs in services.items():
            if dom == "persistent_notification":
                continue  # Skip persistent_notification domain
            for srv, desc in srvs.items():
                if srv in {"reload", "remove", "update", "resttart", "stop"}:
                    continue
                actions.append(
                    {
                        "domain": dom,
                        "service": srv,
                        "description": desc.get("description", ""),
                        "fields": {k: v.get("description", "") for k, v in desc.get("fields", {}).items()},
                    }
                )
        
        # Serialize in a thread pool to avoid blocking
        return await self.hass.async_add_executor_job(
            functools.partial(json.dumps, actions, separators=(",", ":"))
        )