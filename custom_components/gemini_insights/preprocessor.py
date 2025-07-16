"""Preprocessor for Home Assistant data to be sent to Gemini."""
import json
import logging
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.components.recorder import get_instance
from homeassistant.helpers.json import JSONEncoder
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    statistics_during_period,
)

_LOGGER = logging.getLogger(__name__)

SLOT_SECONDS = 30 * 60
SLOTS_PER_DAY = int(timedelta(days=1).total_seconds() // SLOT_SECONDS)


class Preprocessor:
    def __init__(self, hass: HomeAssistant, entity_ids: List[str]):
        self.hass = hass
        self.entity_ids = entity_ids

    async def _compute_long_term_stats(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Return 48 labelled 30-minute averages for the last complete UTC day
        using Home Assistant's built-in long-term statistics.
        """

        def _inner() -> Dict[str, List[Dict[str, Any]]]:
            now_utc = dt_util.utcnow()
            end_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = end_time - timedelta(days=1)

            stats: Dict[str, List[Dict[str, Any]]] = {}

            for entity_id in self.entity_ids:
                # Ask for 5-minute means covering the 24 h window
                raw_rows = statistics_during_period(
                    hass=self.hass,
                    start_time=start_time,
                    end_time=end_time,
                    statistic_ids={entity_id},
                    period="5minute",
                    types={"mean"},
                )

                rows = raw_rows.get(entity_id, [])
                if not rows:
                    # Fallback: fill with None
                    stats[entity_id] = [
                        {
                            "slot_start": (
                                start_time + timedelta(seconds=i * SLOT_SECONDS)
                            ).isoformat(),
                            "avg": None,
                        }
                        for i in range(SLOTS_PER_DAY)
                    ]
                    continue

                # Build a map slot-index -> list of 5-min means
                buckets: Dict[int, List[float]] = {
                    i: [] for i in range(SLOTS_PER_DAY)
                }
                for r in rows:
                    ts = dt_util.utc_from_timestamp(r["start"])
                    slot = int((ts - start_time).total_seconds() // SLOT_SECONDS)
                    if 0 <= slot < SLOTS_PER_DAY:
                        buckets[slot].append(r["mean"])

                stats[entity_id] = [
                    {
                        "slot_start": (
                            start_time + timedelta(seconds=i * SLOT_SECONDS)
                        ).isoformat(),
                        "avg": round(mean(buckets[i]), 2) if buckets[i] else None,
                    }
                    for i in range(SLOTS_PER_DAY)
                ]

            return stats

        return await get_instance(self.hass).async_add_executor_job(_inner)

    async def _fetch_recent_events(self) -> Dict[str, List[Dict[str, Any]]]:
        """Recent raw events (last 6 h) with minimal token usage."""

        def _inner() -> Dict[str, List[Dict[str, Any]]]:
            from homeassistant.components.recorder import history

            now_utc = dt_util.utcnow()
            start_time = now_utc - timedelta(hours=6)

            recent: Dict[str, List[Dict[str, Any]]] = {}
            for entity_id in self.entity_ids:
                try:
                    hist = history.get_significant_states(
                        self.hass,
                        start_time,
                        None,
                        [entity_id],
                        include_start_time_state=True,
                        minimal_response=False,
                    )
                    states = hist.get(entity_id, [])
                    recent[entity_id] = [
                        {
                            "state": s.state,
                            "last_updated": s.last_updated.isoformat(),
                        }
                        for s in states
                    ]
                except Exception as e:
                    _LOGGER.exception(
                        "Error fetching recent events for %s: %s", entity_id, e
                    )
                    recent[entity_id] = []
            return recent

        return await get_instance(self.hass).async_add_executor_job(_inner)

    async def async_get_entity_data_json(self) -> str:
        """Return the unified JSON payload."""
        long_term = await self._compute_long_term_stats()
        recent = await self._fetch_recent_events()
        payload = {"long_term_stats": long_term, "recent_events": recent}
        return json.dumps(payload, cls=JSONEncoder, indent=2)