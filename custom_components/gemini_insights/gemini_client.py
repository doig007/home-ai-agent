"""Client for interacting with the Google Gemini API."""
import logging
# CORRECT: Import the new unified SDK
from google import genai
from google.generativeai import types as genai_types

from .const import CONF_API_KEY

_LOGGER = logging.getLogger(__name__)

# --- [Safety Settings and other constants remain the same] ---
# UPDATED: The class name is now SafetySettingDict in the new SDK
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
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            'insights': genai_types.Schema(type=genai_types.Type.STRING, description="General insights derived from the data."),
            'alerts': genai_types.Schema(type=genai_types.Type.STRING, description="Specific alerts or warnings based on the data."),
            'actions': genai_types.Schema(type=genai_types.Type.STRING, description="Suggested actions or next steps."),
        },
        required=['insights', 'alerts', 'actions']
    )
)

INSIGHTS_TOOL = genai_types.Tool(
    function_declarations=[GENERATE_INSIGHTS_FUNCTION_DECLARATION]
)


class GeminiClient:
    """A client for the Google Gemini API, updated for the new google-genai SDK."""

    def __init__(self, api_key: str):
        """Initialize the Gemini client."""
        if not api_key:
            raise ValueError("Gemini API key is required.")

        # NEW SDK CHANGE: Create a client instance with the API key.
        self._client = genai.Client(api_key=api_key)
        
        self._model_name = "gemini-1.5-flash"
        
        # NEW SDK CHANGE: Get the model from the client.
        self._model = self._client.get_model(f"models/{self._model_name}")
        
        _LOGGER.info(f"Gemini Client initialized for model {self._model_name} using the new genai.Client().")

    def get_insights(self, prompt: str, entity_data_json: str) -> dict | None:
        """
        Get insights from the Gemini API based on the provided prompt and entity data.
        """
        full_prompt = prompt.format(entity_data=entity_data_json)
        _LOGGER.debug(f"Sending prompt to Gemini: {full_prompt[:500]}...")

        gen_config_obj = genai_types.GenerationConfig(
            **BASE_GENERATION_CONFIG_PARAMS
        )

        try:
            # Call generate_content on the model object, which is now separate from the client.
            response = self._model.generate_content(
                contents=full_prompt,
                generation_config=gen_config_obj,
                safety_settings=DEFAULT_SAFETY_SETTINGS,
                tools=[INSIGHTS_TOOL]
            )

            _LOGGER.debug(f"Raw Gemini API response object: {response}")

            # --- [The rest of the response parsing logic remains the same] ---
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