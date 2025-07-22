"""Client for interacting with the Google Gemini API."""
import json
import logging
from typing import Self

import google.generativeai as genai
from google.generativeai import types as genai_types

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# --- [Constants] ---
DEFAULT_SAFETY_SETTINGS = [
    genai_types.SafetySettingDict(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
    genai_types.SafetySettingDict(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
    genai_types.SafetySettingDict(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
    genai_types.SafetySettingDict(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
]

BASE_GENERATION_CONFIG_PARAMS = {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 8192,
}

GENERATE_INSIGHTS_FUNCTION_DECLARATION = genai_types.FunctionDeclaration(
    name="generate_insights",
    description="Generates insights, alerts, actions, and (optionally) any service calls to execute.",
    parameters={
        "type": "object",
        "properties": {
            "insights":  {"type": "string"},
            "alerts":    {"type": "string"},
            "actions":   {"type": "string"},
            "to_execute": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "service": {"type": "string"},
                        "service_data": {"type": "object"},
                    },
                    "required": ["domain", "service", "service_data"],
                },
            },
        },
        "required": ["insights", "alerts", "actions"],
    },
)


INSIGHTS_TOOL = genai_types.Tool(
    function_declarations=[
        GENERATE_INSIGHTS_FUNCTION_DECLARATION
    ]
)


class GeminiClient:
    """A client for the Google Gemini API, using a chat session for context cache."""

    def __init__(self):
        """Initializes the Gemini client with a model and a chat session."""
        self._model_name = "gemini-2.5-flash"
        self._model = genai.GenerativeModel(self._model_name)
        self._chat_session = self._model.start_chat()
        _LOGGER.info(f"Gemini Client initialized for model {self._model_name} with context caching.")

    @classmethod
    async def async_create(cls, hass: HomeAssistant, api_key: str) -> Self:
        """Asynchronously create the GeminiClient by safely configuring the API key."""
        if not api_key:
            raise ValueError("Gemini API key is required.")

        # Configure the API key using a keyword argument in the executor.
        await hass.async_add_executor_job(
            lambda: genai.configure(api_key=api_key)
        )
        
        return cls()

    def get_insights(self, prompt: str, entity_data_json: str, action_schema: str) -> dict | None:
        """Get insights from the Gemini API using the chat session for context."""

        gen_config_obj = genai_types.GenerationConfig(**BASE_GENERATION_CONFIG_PARAMS)

        entity_data = json.loads(entity_data_json or '{}')
        action_data = json.loads(action_schema or '{}') 

        formatted_prompt = prompt.format(
            long_term_stats=entity_data.get("long_term_stats"),
            recent_events=entity_data.get("recent_events"),
            action_schema=action_data
        )

        _LOGGER.debug(f"Sending formatted prompt to Gemini: {formatted_prompt[:500]}...")

        try:
            _LOGGER.error("FORMATTED PROMPT:\n%s", formatted_prompt)

            # Use the chat session to send the message, maintaining context
            response = self._chat_session.send_message(
                content=formatted_prompt,
                generation_config=gen_config_obj,
                safety_settings=DEFAULT_SAFETY_SETTINGS,
                tools=[INSIGHTS_TOOL]
            )
            
            _LOGGER.debug(f"Raw Gemini API response object: {response}")

            if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                _LOGGER.warning("Gemini response did not contain expected content parts. Raw response: %s", response)
                return {"insights": "No content parts in response.", "alerts": "", "actions": "", "raw_text": str(response)}

            function_call = None
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    function_call = part.function_call
                    break
            
            if not function_call:
                text_response = response.text if hasattr(response, 'text') else "N/A"
                _LOGGER.warning("Gemini response did not include a function call. Text response: %s", text_response)
                if hasattr(response, 'text') and response.text:
                    return {"insights": response.text, "alerts": "No function call; direct text response.", "actions": "", "raw_text": response.text}
                return {"insights": "No function call in response and no fallback text.", "alerts": "", "actions": "", "raw_text": str(response)}

            if function_call.name != "generate_insights":
                _LOGGER.warning(f"Gemini called an unexpected function: {function_call.name}. Raw response: {response}")
                return {"insights": f"Unexpected function call: {function_call.name}", "alerts": "", "actions": "", "raw_text": str(response)}

            structured_data = dict(function_call.args)
            _LOGGER.warning("Gemini returned: %s", structured_data)

            # When a function call is returned, response.text is empty.
            # We'll create a JSON string from the structured data as the raw text.
            try:
                args_json = json.dumps(structured_data, indent=4)
                structured_data["raw_text"] = f"Function Call: {function_call.name}\nArguments:\n{args_json}"
            except TypeError:
                _LOGGER.warning("Could not serialize function call arguments to JSON. Falling back to string representation.")
                structured_data["raw_text"] = f"Function Call: {function_call.name}\n" \
                                              f"Arguments: {function_call.args}"

            _LOGGER.info(f"Successfully extracted structured data: {structured_data}")
            return structured_data

        except Exception as e:
            _LOGGER.error(f"Error calling Gemini API or processing its response: {e}")
            if "API key not valid" in str(e) or "PermissionDenied" in str(e) or "API_KEY_INVALID" in str(e).upper():
                 _LOGGER.error("Invalid or unauthorized Gemini API Key.")
            return None
