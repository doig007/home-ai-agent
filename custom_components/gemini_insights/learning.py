"""Persisted household learning support for Gemini Insights."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONFIRMATION_CONFIRMED,
    CONFIRMATION_REJECTED,
    DEFAULT_FORECAST_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_MAX_PATTERNS = 30
_MAX_CONFIRMATIONS = 40
_MAX_PENDING = 10
_MIN_CONFIRMATION_CONFIDENCE = 0.6


def build_confirmation_action(entry_id: str, tag: str, outcome: str) -> str:
    """Build an action string that can be parsed from mobile notifications."""
    return f"{DOMAIN}_{outcome}:{entry_id}:{tag}"


def parse_confirmation_action(action: str | None) -> tuple[str, str, str] | None:
    """Parse a mobile notification action into entry_id, tag, outcome."""
    if not action or ":" not in action:
        return None

    prefix, _, remainder = action.partition(":")
    if prefix == f"{DOMAIN}_{CONFIRMATION_CONFIRMED}":
        outcome = CONFIRMATION_CONFIRMED
    elif prefix == f"{DOMAIN}_{CONFIRMATION_REJECTED}":
        outcome = CONFIRMATION_REJECTED
    else:
        return None

    entry_id, _, tag = remainder.partition(":")
    if not entry_id or not tag:
        return None

    return entry_id, tag, outcome


def build_confirmation_actions(entry_id: str, tag: str) -> list[dict[str, str]]:
    """Build Home Assistant mobile app actions for a confirmation request."""
    return [
        {
            "action": build_confirmation_action(entry_id, tag, CONFIRMATION_CONFIRMED),
            "title": "Yes",
        },
        {
            "action": build_confirmation_action(entry_id, tag, CONFIRMATION_REJECTED),
            "title": "No",
        },
    ]


def _utcnow_iso() -> str:
    """Return the current UTC timestamp as an ISO string."""
    return dt_util.utcnow().isoformat()


def _trim_text(value: Any, limit: int = 280) -> str:
    """Return a normalized string with an upper length bound."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _normalize_pattern(value: str) -> str:
    """Normalize a pattern string for deduplication."""
    return re.sub(r"\s+", " ", value.strip().lower())


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float within the expected range."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default

    return max(0.0, min(1.0, numeric))


def _coerce_entities(value: Any, limit: int = 6) -> list[str]:
    """Convert a candidate entity collection into a clean list of entity ids."""
    if not isinstance(value, list):
        return []

    entities: list[str] = []
    for item in value:
        entity_id = str(item or "").strip()
        if "." not in entity_id or entity_id in entities:
            continue
        entities.append(entity_id)
        if len(entities) >= limit:
            break

    return entities


class HouseholdLearningManager:
    """Persist and merge household learning observations between refreshes."""

    def __init__(self, hass, entry_id: str) -> None:
        """Initialize the learning manager."""
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store(hass, _STORAGE_VERSION, f"{DOMAIN}.{entry_id}.learning")
        self._data: dict[str, Any] | None = None

    async def async_load(self) -> dict[str, Any]:
        """Load learning data from storage."""
        if self._data is not None:
            return self._data

        raw = await self._store.async_load()
        self._data = self._normalize_store(raw or {})
        return self._data

    async def async_get_prompt_payload(self) -> dict[str, Any]:
        """Return the subset of learning data that should be sent back to Gemini."""
        data = await self.async_load()

        patterns = sorted(
            data["patterns"],
            key=lambda item: (
                item.get("status") != CONFIRMATION_CONFIRMED,
                -item.get("confidence", 0.0),
                item.get("updated_at", ""),
            ),
        )[:12]

        pending = sorted(
            data["pending"].values(),
            key=lambda item: item.get("requested_at", ""),
            reverse=True,
        )[:3]

        return {
            "patterns": patterns,
            "recent_confirmations": data["confirmations"][:10],
            "pending_confirmations": pending,
            "last_forecast": data.get("last_forecast"),
        }

    async def async_merge_learning_updates(self, updates: Any) -> bool:
        """Merge model-suggested learning updates into stored household patterns."""
        if not isinstance(updates, list):
            return False

        data = await self.async_load()
        changed = False
        now = _utcnow_iso()

        for item in updates:
            if not isinstance(item, dict):
                continue

            pattern = _trim_text(item.get("pattern"), 240)
            if not pattern:
                continue

            key = _normalize_pattern(pattern)
            if not key:
                continue

            status = str(item.get("status") or "inferred").strip().lower()
            if status not in {"inferred", CONFIRMATION_CONFIRMED, CONFIRMATION_REJECTED}:
                status = "inferred"

            confidence = _coerce_float(item.get("confidence"), default=0.0)
            evidence = _trim_text(item.get("evidence"), 240)
            entities = _coerce_entities(item.get("entities"))

            existing = next(
                (stored for stored in data["patterns"] if stored.get("pattern_key") == key),
                None,
            )
            if existing is None:
                data["patterns"].append(
                    {
                        "pattern": pattern,
                        "pattern_key": key,
                        "status": status,
                        "confidence": confidence,
                        "evidence": evidence,
                        "entities": entities,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                changed = True
                continue

            prior_status = existing.get("status", "inferred")
            if prior_status in {CONFIRMATION_CONFIRMED, CONFIRMATION_REJECTED} and status == "inferred":
                status = prior_status

            if (
                status != existing.get("status")
                or confidence >= existing.get("confidence", 0.0)
                or evidence
                or entities
            ):
                existing.update(
                    {
                        "pattern": pattern,
                        "status": status,
                        "confidence": max(confidence, existing.get("confidence", 0.0)),
                        "evidence": evidence or existing.get("evidence", ""),
                        "entities": entities or existing.get("entities", []),
                        "updated_at": now,
                    }
                )
                changed = True

        if changed:
            self._trim_patterns(data)
            await self._store.async_save(data)

        return changed

    async def async_store_forecast(self, forecast: str | None, hours: int = DEFAULT_FORECAST_HOURS) -> None:
        """Persist the latest forecast for future context."""
        if not forecast:
            return

        data = await self.async_load()
        data["last_forecast"] = {
            "forecast": _trim_text(forecast, 500),
            "hours": hours,
            "generated_at": _utcnow_iso(),
        }
        await self._store.async_save(data)

    async def async_queue_confirmation_requests(
        self,
        requests: Any,
        latest_states: dict[str, Any],
        max_requests: int,
    ) -> list[dict[str, Any]]:
        """Persist a small set of pending confirmation requests."""
        if max_requests <= 0 or not isinstance(requests, list):
            return []

        data = await self.async_load()
        queued: list[dict[str, Any]] = []
        now = _utcnow_iso()

        recent_pattern_keys = {
            item.get("pattern_key")
            for item in data["confirmations"][:10]
            if item.get("pattern_key")
        }
        pending_pattern_keys = {
            item.get("pattern_key")
            for item in data["pending"].values()
            if item.get("pattern_key")
        }

        candidates = sorted(
            (item for item in requests if isinstance(item, dict)),
            key=lambda item: _coerce_float(item.get("confidence"), default=0.0),
            reverse=True,
        )

        for item in candidates:
            if len(queued) >= max_requests:
                break

            pattern = _trim_text(item.get("pattern"), 240)
            question = _trim_text(item.get("question"), 180)
            if not pattern or not question:
                continue

            confidence = _coerce_float(item.get("confidence"), default=0.0)
            if confidence < _MIN_CONFIRMATION_CONFIDENCE:
                continue

            pattern_key = _normalize_pattern(pattern)
            if not pattern_key or pattern_key in recent_pattern_keys or pattern_key in pending_pattern_keys:
                continue

            tag = hashlib.sha1(f"{self.entry_id}:{pattern_key}".encode("utf-8")).hexdigest()[:12]
            if tag in data["pending"]:
                continue

            entities = _coerce_entities(item.get("entities"))
            snapshot = {
                entity_id: latest_states[entity_id]
                for entity_id in entities
                if entity_id in latest_states
            }
            pending = {
                "tag": tag,
                "pattern": pattern,
                "pattern_key": pattern_key,
                "question": question,
                "reason": _trim_text(item.get("reason"), 220),
                "confidence": confidence,
                "entities": entities,
                "snapshot": snapshot,
                "requested_at": now,
            }
            data["pending"][tag] = pending
            queued.append(pending)
            pending_pattern_keys.add(pattern_key)

        if queued:
            self._trim_pending(data)
            await self._store.async_save(data)

        return queued

    async def async_record_confirmation(
        self,
        tag: str,
        outcome: str,
        source: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Record a confirmation outcome and feed it back into household learning."""
        if outcome not in {CONFIRMATION_CONFIRMED, CONFIRMATION_REJECTED}:
            return None

        data = await self.async_load()
        pending = data["pending"].pop(tag, None)
        if pending is None:
            _LOGGER.debug("Ignoring confirmation for unknown tag %s on entry %s", tag, self.entry_id)
            return None

        now = _utcnow_iso()
        confirmation = {
            "tag": tag,
            "pattern": pending.get("pattern", ""),
            "pattern_key": pending.get("pattern_key", ""),
            "question": pending.get("question", ""),
            "reason": pending.get("reason", ""),
            "entities": pending.get("entities", []),
            "snapshot": pending.get("snapshot", {}),
            "requested_at": pending.get("requested_at"),
            "answered_at": now,
            "outcome": outcome,
            "source": source,
            "notes": _trim_text(notes, 220),
        }
        data["confirmations"].insert(0, confirmation)
        data["confirmations"] = data["confirmations"][:_MAX_CONFIRMATIONS]

        self._upsert_pattern_from_confirmation(data, confirmation, now)
        await self._store.async_save(data)
        return confirmation

    def _normalize_store(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize persisted storage to the expected shape."""
        return {
            "patterns": [item for item in raw.get("patterns", []) if isinstance(item, dict)],
            "confirmations": [
                item for item in raw.get("confirmations", []) if isinstance(item, dict)
            ][: _MAX_CONFIRMATIONS],
            "pending": {
                key: value
                for key, value in raw.get("pending", {}).items()
                if isinstance(key, str) and isinstance(value, dict)
            },
            "last_forecast": raw.get("last_forecast"),
        }

    def _trim_patterns(self, data: dict[str, Any]) -> None:
        """Trim stored patterns to the most useful recent entries."""
        data["patterns"] = sorted(
            data["patterns"],
            key=lambda item: (
                item.get("status") != CONFIRMATION_CONFIRMED,
                -item.get("confidence", 0.0),
                item.get("updated_at", ""),
            ),
        )[:_MAX_PATTERNS]

    def _trim_pending(self, data: dict[str, Any]) -> None:
        """Trim the pending queue down to the configured cap."""
        pending_items = sorted(
            data["pending"].values(),
            key=lambda item: item.get("requested_at", ""),
            reverse=True,
        )[:_MAX_PENDING]
        data["pending"] = {item["tag"]: item for item in pending_items}

    def _upsert_pattern_from_confirmation(
        self,
        data: dict[str, Any],
        confirmation: dict[str, Any],
        now: str,
    ) -> None:
        """Apply a confirmation outcome to the stored household pattern list."""
        pattern = confirmation.get("pattern", "")
        pattern_key = confirmation.get("pattern_key", "")
        if not pattern or not pattern_key:
            return

        existing = next(
            (stored for stored in data["patterns"] if stored.get("pattern_key") == pattern_key),
            None,
        )

        payload = {
            "pattern": pattern,
            "pattern_key": pattern_key,
            "status": confirmation.get("outcome"),
            "confidence": 1.0,
            "evidence": confirmation.get("reason", ""),
            "entities": confirmation.get("entities", []),
            "updated_at": now,
        }
        if confirmation.get("notes"):
            payload["evidence"] = _trim_text(
                f"{payload['evidence']} Notes: {confirmation['notes']}".strip(),
                240,
            )

        if existing is None:
            payload["created_at"] = now
            data["patterns"].append(payload)
        else:
            existing.update(payload)

        self._trim_patterns(data)
