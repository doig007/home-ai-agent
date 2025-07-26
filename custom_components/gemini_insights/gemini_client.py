"""Client for interacting with the Google Gemini API (google-genai SDK)."""
import json
import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types as t

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MODEL = "gemini-1.5-flash"
SAFETY = {
    "HARASSMENT":          "BLOCK_MEDIUM_AND_ABOVE",
    "HATE_SPEECH":         "BLOCK_MEDIUM_AND_ABOVE",
    "SEXUALLY_EXPLICIT":   "BLOCK_MEDIUM_AND_ABOVE",
    "DANGEROUS_CONTENT":   "BLOCK_MEDIUM_AND_ABOVE",
}

GEN_CFG = t.GenerateContentConfig(
    temperature=0.0,
    max_output_tokens=2048,
    response_mime_type="application/json",
    response_schema={
        "type": "object",
        "properties": {
            "insights": {"type": "string"},
            "alerts":   {"type": "string"},
            "actions":  {"type": "string"},
            "to_execute": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain":       {"type": "string"},
                        "service":      {"type": "string"},
                        "service_data": {"type": "object"},
                    },
                    "required": ["domain", "service", "service_data"],
                },
            },
        },
        "required": ["insights", "alerts", "actions"],
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

        client = genai.Client(
            vertexai=False,
            api_key=api_key,
            http_options=t.HttpOptions(api_version="v1beta"),
        )

        # Verify key with a tiny test call
        try:
            await hass.async_add_executor_job(
                client.models.generate_content,
                "gemini-1.5-flash",
                ["ping"],
                t.GenerateContentConfig(max_output_tokens=1),
            )
        except Exception as exc:
            _LOGGER.error("Gemini key test failed: %s", exc)
            raise ValueError("Invalid or unauthorized Gemini API key") from exc

        return cls(client)

    async def get_insights(
        self,
        prompt_template: str,
        entity_data_json: str,
        action_schema: str,
    ) -> Optional[Dict[str, Any]]:
        """Return parsed JSON from Gemini."""
        entity_data = json.loads(entity_data_json or "{}")
        final_prompt = prompt_template.format(
            long_term_stats=entity_data.get("long_term_stats"),
            recent_events=entity_data.get("recent_events"),
            action_schema=json.loads(action_schema or "[]"),
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=MODEL,
                contents=[final_prompt],
                config=GEN_CFG,
            )
            return json.loads(response.text)
        except Exception as exc:
            _LOGGER.exception("Gemini call failed")
            return None