"""Client for interacting with the Google Gemini API (google-genai SDK)."""
import asyncio
import json
import logging
from typing import Any, Dict, Iterable, Optional

from aiohttp import ClientConnectionError, ClientConnectorError, ClientError
from google import genai
from google.genai import types as t

from homeassistant.core import HomeAssistant

from .const import DEFAULT_MODEL

_LOGGER = logging.getLogger(__name__)

SAFETY = {
    "HARASSMENT":          "BLOCK_MEDIUM_AND_ABOVE",
    "HATE_SPEECH":         "BLOCK_MEDIUM_AND_ABOVE",
    "SEXUALLY_EXPLICIT":   "BLOCK_MEDIUM_AND_ABOVE",
    "DANGEROUS_CONTENT":   "BLOCK_MEDIUM_AND_ABOVE",
}

GEN_CFG = t.GenerateContentConfig(
    temperature=0.9,
    max_output_tokens=4096,
    response_mime_type="application/json",
    response_schema={
        "type": "object",
        "properties": {
            "insights": {"type": "string"},
            "alerts":   {"type": "string"},
            "forecast": {"type": "string"},
            "to_execute": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain":       {"type": "string"},
                        "service":      {"type": "string"},
                        "service_data": {"type": "string"},
                        "confidence":   {"type": "number", "description": "Confidence in the action from 0.0 to 1.0"},
                    },
                    "required": ["domain", "service", "service_data","confidence"],
                },
            },
            "learning_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "status": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {"type": "string"},
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["pattern", "status", "confidence", "evidence"],
                },
            },
            "confirmation_requests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "pattern": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"type": "number"},
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["question", "pattern", "reason", "confidence"],
                },
            },
        },
        "required": [
            "insights",
            "alerts",
            "forecast",
            "to_execute",
            "learning_updates",
            "confirmation_requests",
        ],
    },
)


class GeminiClient:
    """Thin async wrapper around google-genai client."""

    def __init__(self, hass: HomeAssistant, client: genai.Client, model: str):
        self._hass = hass
        self._client = client
        self._model = model
        self._aio_models = getattr(getattr(client, "aio", None), "models", None)

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, api_key: str, model: str = DEFAULT_MODEL
    ) -> "GeminiClient":
        """Build and return the wrapped client."""
        if not api_key:
            raise ValueError("API key missing")

        selected_model = (model or DEFAULT_MODEL).strip()
        if not selected_model:
            raise ValueError("Model missing")

        try:
            client = await hass.async_add_executor_job(_build_client, api_key, selected_model)
        except Exception as exc:
            error_type, error_message = _classify_exception(exc)
            if error_type in {"network_unreachable", "dns_error", "timeout"}:
                _LOGGER.warning("Gemini connectivity test failed: %s", error_message)
                raise ConnectionError(error_message) from exc

            _LOGGER.error("Gemini key test failed: %s", error_message)
            raise ValueError("Invalid or unauthorized Gemini API key") from exc

        return cls(hass, client, selected_model)

    async def get_insights(
        self,
        final_prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """Return parsed JSON from Gemini using a fully-formed prompt."""

        try:
            response = await self._async_generate_content(final_prompt)
            payload = json.loads(response.text)
            payload.setdefault("forecast", "")
            payload.setdefault("to_execute", [])
            payload.setdefault("learning_updates", [])
            payload.setdefault("confirmation_requests", [])
            payload["raw_text"] = response.text
            return payload
        except Exception as exc:
            error_type, error_message = _classify_exception(exc)
            if error_type in {"network_unreachable", "dns_error", "timeout"}:
                _LOGGER.warning("Gemini API call failed: %s", error_message)
            else:
                _LOGGER.exception("Gemini API call failed")
            return _build_error_payload(error_type, error_message)

    async def _async_generate_content(self, final_prompt: str):
        """Generate content using the SDK's async API when available."""
        if self._aio_models is not None:
            return await self._aio_models.generate_content(
                model=self._model,
                contents=[final_prompt],
                config=GEN_CFG,
            )

        return await self._hass.async_add_executor_job(
            _generate_content_sync,
            self._client,
            self._model,
            final_prompt,
        )


def _build_client(api_key: str, model: str):
    """Blocking helper: create client and do a tiny call."""
    import google.genai as genai
    from google.genai import types as t

    client = genai.Client(
        vertexai=False,
        api_key=api_key,
        http_options=t.HttpOptions(api_version="v1beta"),
    )
    # quick smoke test
    client.models.generate_content(
        model=model,
        contents=["ping"],
        config=t.GenerateContentConfig(max_output_tokens=1),
    )
    return client


def _generate_content_sync(client: genai.Client, model: str, final_prompt: str):
    """Executor-safe sync fallback for SDK builds without aio support."""
    return client.models.generate_content(
        model=model,
        contents=[final_prompt],
        config=GEN_CFG,
    )


def _iter_exception_chain(exc: BaseException) -> Iterable[BaseException]:
    """Yield an exception and its chained causes/contexts."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        yield current
        seen.add(id(current))
        current = current.__cause__ or current.__context__


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Classify Gemini client failures into a small set of user-meaningful errors."""
    chain = list(_iter_exception_chain(exc))
    combined = " | ".join(str(item) for item in chain if str(item)).lower()

    if "network unreachable" in combined or any(
        isinstance(item, (ClientConnectorError, ClientConnectionError, OSError))
        and "network unreachable" in str(item).lower()
        for item in chain
    ):
        return (
            "network_unreachable",
            "Network unreachable: Home Assistant could not reach generativelanguage.googleapis.com:443. "
            "Check internet access, container networking, firewall rules, and IPv4/IPv6 routing.",
        )

    if any(isinstance(item, asyncio.TimeoutError) for item in chain) or "timed out" in combined:
        return (
            "timeout",
            "Connection to the Gemini API timed out. Check Home Assistant outbound connectivity "
            "and try again.",
        )

    if any(isinstance(item, (ClientConnectorError, ClientConnectionError, ClientError)) for item in chain):
        if any(
            marker in combined
            for marker in (
                "temporary failure in name resolution",
                "name or service not known",
                "nodename nor servname",
                "no address associated",
            )
        ):
            return (
                "dns_error",
                "DNS lookup failed for generativelanguage.googleapis.com. Check your Home Assistant "
                "DNS configuration and outbound network access.",
            )
        return (
            "connection_error",
            "Home Assistant could not connect to the Gemini API. Check outbound network access "
            "and any proxy or firewall rules.",
        )

    if any(marker in combined for marker in ("401", "403", "unauthorized", "permission denied")):
        return (
            "auth_error",
            "Gemini rejected the request. Check that the API key is valid and allowed to use the selected model.",
        )

    if "json" in combined and "decode" in combined:
        return (
            "invalid_response",
            "Gemini returned a response the integration could not parse as JSON.",
        )

    message = next((str(item) for item in chain if str(item)), exc.__class__.__name__)
    return ("unknown_error", f"Gemini request failed: {message}")


def _build_error_payload(error_type: str, error_message: str) -> Dict[str, Any]:
    """Build a structured error payload instead of returning None."""
    return {
        "insights": error_message,
        "alerts": "Gemini request failed.",
        "forecast": "",
        "to_execute": [],
        "learning_updates": [],
        "confirmation_requests": [],
        "error_type": error_type,
        "error_message": error_message,
        "raw_text": error_message,
    }
