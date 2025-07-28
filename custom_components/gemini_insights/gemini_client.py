"""Client for interacting with the Google Gemini API (google-genai SDK)."""
import json
import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types as t

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
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
        },
        "required": ["insights", "alerts"],
    },
)


class GeminiClient:
    """Thin async wrapper around google-genai client."""

    def __init__(self, client: genai.Client):
        self._client = client

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, api_key: str
    ) -> "GeminiClient":
        """Build and return the wrapped client."""
        if not api_key:
            raise ValueError("API key missing")

        try:
            client = await hass.async_add_executor_job(_build_client, api_key)
        except Exception as exc:
            _LOGGER.error("Gemini key test failed: %s", exc)
            raise ValueError("Invalid or unauthorized Gemini API key") from exc

        return cls(client)

    async def get_insights(
        self,
        final_prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """Return parsed JSON from Gemini using a fully-formed prompt."""

        try:
            response = await self._client.aio.models.generate_content(
                model=MODEL,
                contents=[final_prompt],
                generation_config=GEN_CFG,
                safety_settings=SAFETY,
            )
            # The response.text should already be a JSON string due to response_mime_type
            return json.loads(response.text)
        except Exception:
            _LOGGER.exception("Gemini API call failed")
            return None


def _build_client(api_key: str):
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
        model="gemini-2.5-flash",
        contents=["ping"],
        config=t.GenerateContentConfig(max_output_tokens=1),
    )
    return client