import functools
import json
from collections import Counter
from datetime import datetime
from statistics import mean
from typing import Any

from homeassistant.components.recorder.models import LazyState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry, entity_registry
from homeassistant.helpers.json import JSONEncoder
from homeassistant.util import dt as dt_util


class Preprocessor:
    """Format Home Assistant data into compact, model-friendly payloads."""

    def __init__(self, hass: HomeAssistant, entity_ids: list[str]):
        """Initialize the preprocessor."""
        self.hass = hass
        self.entity_ids = entity_ids

    def _is_numeric_entity(self, entity_id: str) -> bool:
        """Check whether an entity currently has a numeric state."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        try:
            float(state.state)
            return True
        except (ValueError, TypeError):
            return False

    def _extract_state_and_time(
        self,
        item: State | LazyState | dict[str, Any],
    ) -> tuple[str | None, datetime | None]:
        """Extract a state value and timestamp from recorder history."""
        if isinstance(item, LazyState):
            return item.state, item.last_updated

        if isinstance(item, State):
            return item.state, item.last_updated

        if isinstance(item, dict):
            state_value = item.get("s")
            last_updated = item.get("lu")
            if last_updated is None:
                return state_value, None
            return state_value, dt_util.utc_from_timestamp(last_updated)

        return None, None

    async def async_get_latest_states(self) -> dict[str, dict[str, Any]]:
        """Return the latest compact state payload for all tracked entities."""
        payload: dict[str, dict[str, Any]] = {}
        for entity_id in self.entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            payload[entity_id] = {
                "s": state.state,
                "lc": state.last_changed.isoformat(),
            }

        return payload

    async def async_get_compact_latest_states_json(self) -> str:
        """Return a compact JSON string of the latest states."""
        payload = await self.async_get_latest_states()
        return await self.hass.async_add_executor_job(json.dumps, payload, cls=JSONEncoder)

    async def async_get_compact_long_term_stats(
        self,
        stats: dict[str, list[dict[str, Any]]],
        start_time: datetime,
    ) -> dict[str, dict[int, float]]:
        """Return 48 half-hour slots with averaged long-term stats."""
        if not stats:
            return {}

        entity_stats: dict[str, dict[int, list[float]]] = {
            entity_id: {slot: [] for slot in range(48)} for entity_id in self.entity_ids
        }

        for entity_id, stat_list in stats.items():
            if not self._is_numeric_entity(entity_id):
                continue

            for row in stat_list:
                timestamp = dt_util.utc_from_timestamp(row["start"])
                slot = int((timestamp - start_time).total_seconds() // 1800)
                if 0 <= slot < 48 and row.get("mean") is not None:
                    entity_stats[entity_id][slot].append(row["mean"])

        compact_payload: dict[str, dict[int, float]] = {}
        for entity_id, slots in entity_stats.items():
            entity_payload = {
                slot: round(mean(values), 2)
                for slot, values in slots.items()
                if values
            }
            if entity_payload:
                compact_payload[entity_id] = entity_payload

        return compact_payload

    async def async_get_compact_long_term_stats_json(
        self,
        stats: dict[str, list[dict[str, Any]]],
        start_time: datetime,
    ) -> str:
        """Return long-term statistics as JSON."""
        payload = await self.async_get_compact_long_term_stats(stats, start_time)
        json_job = functools.partial(json.dumps, payload, cls=JSONEncoder)
        return await self.hass.async_add_executor_job(json_job)

    async def async_get_compact_recent_events(
        self,
        history: dict[str, list[State | LazyState | dict[str, Any]]],
    ) -> dict[str, list[dict[str, str | None]]]:
        """Return a compact payload of recent state changes."""
        if not history:
            return {}

        payload: dict[str, list[dict[str, str | None]]] = {}
        for entity_id, states in history.items():
            if not states:
                continue

            compact_states: list[dict[str, str | None]] = []
            for item in states:
                state_value, timestamp = self._extract_state_and_time(item)
                if state_value is None:
                    continue
                compact_states.append(
                    {
                        "s": state_value,
                        "t": timestamp.isoformat() if timestamp else None,
                    }
                )

            if compact_states:
                payload[entity_id] = compact_states

        return payload

    async def async_get_compact_recent_events_json(
        self,
        history: dict[str, list[State | LazyState | dict[str, Any]]],
    ) -> str:
        """Return recent state changes as JSON."""
        payload = await self.async_get_compact_recent_events(history)
        json_job = functools.partial(json.dumps, payload, cls=JSONEncoder)
        return await self.hass.async_add_executor_job(json_job)

    async def async_get_entity_context(self) -> dict[str, dict[str, Any]]:
        """Return helpful metadata for the tracked entities."""
        entity_reg = entity_registry.async_get(self.hass)
        area_reg = area_registry.async_get(self.hass)

        payload: dict[str, dict[str, Any]] = {}
        for entity_id in self.entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue

            entry = entity_reg.async_get(entity_id)
            area_name = None
            if entry and entry.area_id:
                area = area_reg.async_get_area(entry.area_id)
                area_name = area.name if area else None

            payload[entity_id] = {
                "name": state.name,
                "domain": entity_id.split(".", 1)[0],
                "area": area_name,
                "device_class": state.attributes.get("device_class"),
                "unit": state.attributes.get("unit_of_measurement"),
                "state_class": state.attributes.get("state_class"),
            }

        return payload

    async def async_get_entity_context_json(self) -> str:
        """Return entity metadata as JSON."""
        payload = await self.async_get_entity_context()
        return await self.hass.async_add_executor_job(json.dumps, payload, cls=JSONEncoder)

    async def async_get_behavior_summary(
        self,
        history: dict[str, list[State | LazyState | dict[str, Any]]],
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        """Return a compact summary of entity activity across the history window."""
        latest_states = await self.async_get_latest_states()
        if not history:
            return {
                "window_start": start_time.isoformat(),
                "window_end": end_time.isoformat(),
                "note": "No recorder history was available for this refresh.",
                "entities": {
                    entity_id: {
                        "current_state": state.get("s"),
                        "last_changed": state.get("lc"),
                        "change_count": 0,
                    }
                    for entity_id, state in latest_states.items()
                },
            }

        overall_hours: Counter[int] = Counter()
        change_counts: list[dict[str, Any]] = []
        entity_summaries: dict[str, dict[str, Any]] = {}

        for entity_id in self.entity_ids:
            current_state = latest_states.get(entity_id, {})
            states = history.get(entity_id, [])
            state_counter: Counter[str] = Counter()
            hour_counter: Counter[int] = Counter()
            weekday_counter: Counter[str] = Counter()
            last_timestamp: datetime | None = None
            event_count = 0

            for item in states:
                state_value, timestamp = self._extract_state_and_time(item)
                if state_value is None:
                    continue
                state_counter[str(state_value)] += 1
                event_count += 1
                if timestamp is not None:
                    hour_counter[timestamp.hour] += 1
                    weekday_counter[timestamp.strftime("%a")] += 1
                    last_timestamp = timestamp

            overall_hours.update(hour_counter)
            change_count = max(event_count - 1, 0)
            change_counts.append({"entity_id": entity_id, "change_count": change_count})
            entity_summaries[entity_id] = {
                "current_state": current_state.get("s"),
                "last_changed": current_state.get("lc"),
                "change_count": change_count,
                "observed_states": dict(state_counter.most_common(4)),
                "active_hours": [hour for hour, _ in hour_counter.most_common(3)],
                "active_days": [day for day, _ in weekday_counter.most_common(3)],
                "latest_history_event": last_timestamp.isoformat() if last_timestamp else None,
            }

        return {
            "window_start": start_time.isoformat(),
            "window_end": end_time.isoformat(),
            "busiest_hours": [hour for hour, _ in overall_hours.most_common(5)],
            "most_active_entities": sorted(
                change_counts,
                key=lambda item: item["change_count"],
                reverse=True,
            )[:5],
            "entities": entity_summaries,
        }

    async def async_get_behavior_summary_json(
        self,
        history: dict[str, list[State | LazyState | dict[str, Any]]],
        start_time: datetime,
        end_time: datetime,
    ) -> str:
        """Return the behavior summary as JSON."""
        payload = await self.async_get_behavior_summary(history, start_time, end_time)
        return await self.hass.async_add_executor_job(json.dumps, payload, cls=JSONEncoder)

    async def async_get_action_schema(self) -> str:
        """Return a compact JSON list of allowed Home Assistant actions."""
        from homeassistant.helpers import service

        services = await service.async_get_all_descriptions(self.hass)

        actions = []
        for domain, service_map in services.items():
            if domain == "persistent_notification":
                continue

            for service_name, description in service_map.items():
                if service_name in {"reload", "remove", "update", "restart", "stop"}:
                    continue
                actions.append(
                    {
                        "domain": domain,
                        "service": service_name,
                        "description": description.get("description", ""),
                        "fields": {
                            key: value.get("description", "")
                            for key, value in description.get("fields", {}).items()
                        },
                    }
                )

        json_job = functools.partial(json.dumps, actions, separators=(",", ":"))
        return await self.hass.async_add_executor_job(json_job)
