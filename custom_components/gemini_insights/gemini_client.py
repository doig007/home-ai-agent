"""Client for interacting with the Google Gemini API (google-genai SDK)."""
import json
import logging
from typing import Any, Dict, Optional

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
            _LOGGER.error("Gemini key test failed: %s", exc)
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
        except Exception:
            _LOGGER.exception("Gemini API call failed")
            return None

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
