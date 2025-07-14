"""Preprocessor for Home Assistant data to be sent to Gemini."""
import json
import logging
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.components.recorder import history
from homeassistant.helpers.json import JSONEncoder
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# 30-minute buckets → 48 per day
SLOT_SECONDS = 30 * 60
SLOTS_PER_DAY = int(timedelta(days=1).total_seconds() // SLOT_SECONDS)


class Preprocessor:
    """
    Handles fetching and preprocessing of Home Assistant data for the Gemini API.
    """

    def __init__(self, hass: HomeAssistant, entity_ids: List[str]):
        self.hass = hass
        self.entity_ids = entity_ids
        self.last_updated = None  # not used for the new logic, but kept for compat

    # ------------------------------------------------------------------
    # NEW: compute 48 half-hour averages for the last full calendar day
    # ------------------------------------------------------------------
    def _compute_long_term_stats(self) -> Dict[str, List[float]]:
        """
        Return a dict keyed by entity_id with 48 half-hour averages
        for the last complete day.
        """
        end_time = dt_util.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )  # start of today
        start_time = end_time - timedelta(days=1)

        stats: Dict[str, List[float]] = {}

        for entity_id in self.entity_ids:
            try:
                hist = history.get_significant_states(
                    self.hass,
                    start_time,
                    end_time,
                    [entity_id],
                    include_start_time_state=True,
                    minimal_response=False,
                )
                states = hist.get(entity_id, [])
                if not states:
                    stats[entity_id] = [None] * SLOTS_PER_DAY
                    continue

                # bucket[t] will collect numeric state values
                buckets: Dict[int, List[float]] = {i: [] for i in range(SLOTS_PER_DAY)}

                for s in states:
                    try:
                        val = float(s.state)
                    except (ValueError, TypeError):
                        continue  # skip non-numeric

                    slot = int(
                        (s.last_updated.replace(tzinfo=None) - start_time).total_seconds()
                        // SLOT_SECONDS
                    )
                    if 0 <= slot < SLOTS_PER_DAY:
                        buckets[slot].append(val)

                # compute mean for each bucket
                stats[entity_id] = [
                    round(mean(buckets[i]), 2) if buckets[i] else None
                    for i in range(SLOTS_PER_DAY)
                ]

            except Exception as e:
                _LOGGER.exception(
                    "Error computing long-term stats for %s: %s", entity_id, e
                )
                stats[entity_id] = [None] * SLOTS_PER_DAY

        return stats

    # ------------------------------------------------------------------
    # NEW: fetch recent raw events (last 6 hours by default)
    # ------------------------------------------------------------------
    async def _fetch_recent_events(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Return recent raw events for each entity (last 6 h default).
        """
        now = dt_util.utcnow()
        start_time = now - timedelta(hours=6)

        recent: Dict[str, List[Dict[str, Any]]] = {}

        for entity_id in self.entity_ids:
            try:
                hist = await self.hass.async_add_executor_job(
                    history.get_significant_states,
                    self.hass,
                    start_time,
                    None,
                    [entity_id],
                    None,
                    True,
                    False,
                )
                states = hist.get(entity_id, [])
                recent[entity_id] = [
                    {
                        "state": s.state,
                        "last_changed": s.last_changed.isoformat(),
                        "last_updated": s.last_updated.isoformat(),
                    }
                    for s in states
                ]
            except Exception as e:
                _LOGGER.exception("Error fetching recent events for %s: %s", entity_id, e)
                recent[entity_id] = []

        return recent

    # ------------------------------------------------------------------
    # Public: build the new JSON payload
    # ------------------------------------------------------------------
    async def async_get_entity_data_json(self) -> str:
        """
        Returns JSON with:
        {
          "long_term_stats": { "sensor.x": [48 floats] },
          "recent_events":   { "sensor.x": [...] }
        }
        """
        long_term = await self.hass.async_add_executor_job(
            self._compute_long_term_stats
        )
        recent = await self._fetch_recent_events()

        payload = {
            "long_term_stats": long_term,
            "recent_events": recent,
        }
        return json.dumps(payload, cls=JSONEncoder, indent=2)