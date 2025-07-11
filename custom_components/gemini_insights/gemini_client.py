"""Client for interacting with the Google Gemini API."""
import logging
from typing import Self

# Correct import for the library version that uses .configure()
import google.generativeai as genai
from google.generativeai import types as genai_types

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# --- [Constants are correct and unchanged] ---
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
    description="Generates insights, alerts, and actions based on the provided data.",
    parameters={
        'type': 'object',
        'properties': {
            'insights': {'type': 'string', 'description': "General insights derived from the data."},
            'alerts': {'type': 'string', 'description': "Specific alerts or warnings based on the data."},
            'actions': {'type': 'string', 'description': "Suggested actions or next steps."},
        },
        'required': ['insights', 'alerts', 'actions']
    }
)

INSIGHTS_TOOL = genai_types.Tool(
    function_declarations=[GENERATE_INSIGHTS_FUNCTION_DECLARATION]
)


class GeminiClient:
    """A client for the Google Gemini API, using the correct initialization."""

    def __init__(self):
        """Initializes the Gemini client with a model."""
        self._model_name = "gemini-1.5-flash"
        self._model = genai.GenerativeModel(self._model_name)
        _LOGGER.info(f"Gemini Client initialized for model {self._model_name}")

    @classmethod
    async def async_create(cls, hass: HomeAssistant, api_key: str) -> Self:
        """Asynchronously create the GeminiClient by safely configuring the API key."""
        if not api_key:
            raise ValueError("Gemini API key is required.")

        # === FINAL FIX ===
        # The error "configure() takes 0 positional arguments but 1 was given" means
        # we MUST call it with a keyword argument, like genai.configure(api_key=...).
        # We use a lambda here to pass this keyword argument call to the executor.
        await hass.async_add_executor_job(
            lambda: genai.configure(api_key=api_key)
        )
        
        # Now that the API key is configured globally, we can instantiate the class.
        return cls()

    def get_insights(self, prompt: str, entity_data_json: str) -> dict | None:
        """Get insights from the Gemini API. This method remains synchronous."""
        # ... [The rest of this method is correct and unchanged] ...
        full_prompt = prompt.format(entity_data=entity_data_json)
        _LOGGER.debug(f"Sending prompt to Gemini: {full_prompt[:500]}...")

        gen_config_obj = genai_types.GenerationConfig(**BASE_GENERATION_CONFIG_PARAMS)

        try:
            response = self._model.generate_content(
                contents=full_prompt,
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
            structured_data["raw_text"] = response.text if hasattr(response, 'text') else ""

            _LOGGER.info(f"Successfully extracted structured data: {structured_data}")
            return structured_data

        except Exception as e:
            _LOGGER.error(f"Error calling Gemini API or processing its response: {e}")
            if "API key not valid" in str(e) or "PermissionDenied" in str(e) or "API_KEY_INVALID" in str(e).upper():
                 _LOGGER.error("Invalid or unauthorized Gemini API Key.")
            return None
