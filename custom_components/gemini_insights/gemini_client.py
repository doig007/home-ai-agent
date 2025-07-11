"""Client for interacting with the Google Gemini API."""
import logging
from google import genai
from google.genai import types

from .const import CONF_API_KEY

_LOGGER = logging.getLogger(__name__)

# Safety settings to block harmful content. Adjust as needed.
# Refer to https://ai.google.dev/gemini-api/docs/safety-settings
DEFAULT_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
]

# Generation configuration for the model
# Refer to https://ai.google.dev/gemini-api/docs/config
DEFAULT_GENERATION_CONFIG = types.GenerateContentConfig(
    temperature=0.7,
    top_p=1,
    top_k=1,
    max_output_tokens=64000, # Adjust as needed, up to model limits
)

# Define the schema for the structured response
# In the new SDK, this is defined directly as part of the FunctionDeclaration's parameters.
# We will use a dictionary for clarity here, which will be part of the FunctionDeclaration.
RESPONSE_SCHEMA_DICT = {
    "type": "object",
    "properties": {
        "insights": {"type": "string", "description": "General insights derived from the data."},
        "alerts": {"type": "string", "description": "Specific alerts or warnings based on the data."},
        "actions": {"type": "string", "description": "Suggested actions or next steps."},
    },
    "required": ["insights", "alerts", "actions"],
}

# Define the function declaration for Gemini
GENERATE_INSIGHTS_FUNCTION = types.FunctionDeclaration(
    name="generate_insights",
    description="Generates insights, alerts, and actions based on the provided data.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            'insights': types.Schema(type=types.Type.STRING, description="General insights derived from the data."),
            'alerts': types.Schema(type=types.Type.STRING, description="Specific alerts or warnings based on the data."),
            'actions': types.Schema(type=types.Type.STRING, description="Suggested actions or next steps."),
        },
        required=['insights', 'alerts', 'actions']
    )
)

# Define the tool for Gemini
INSIGHTS_TOOL = types.Tool(
    function_declarations=[GENERATE_INSIGHTS_FUNCTION]
)

class GeminiClient:
    """A client for the Google Gemini API."""

    def __init__(self, api_key: str):
        """Initialize the Gemini client."""
        if not api_key:
            raise ValueError("Gemini API key is required.")
        # In the new SDK, the API key is typically set via an environment variable (GEMINI_API_KEY)
        # or passed directly to the client.
        # For this custom component, direct passing is more appropriate.
        self._client = genai.Client(api_key=api_key)
        # Model interaction is now through client.models.<method>
        # The model name, config, safety settings, and tools are passed to each call.
        self._model_name = "gemini-1.5-flash" # Changed from 2.5-flash, check availability
        _LOGGER.info(f"Gemini Client initialized for model {self._model_name} and insights tool")

    def get_insights(self, prompt: str, entity_data_json: str) -> dict | None:
        """
        Get insights from the Gemini API based on the provided prompt and entity data.
        The response will be structured according to RESPONSE_SCHEMA.

        Args:
            prompt: The base prompt template.
            entity_data_json: A JSON string of the Home Assistant entity data.

        Returns:
        The response will be structured according to RESPONSE_SCHEMA.
            or None if an error occurs.
        """
        full_prompt = prompt.format(entity_data=entity_data_json)
        # It's generally better to send the structured data as part of the message
        # if the API supports it, rather than just a JSON string within a larger prompt.
        # However, for now, we'll stick to the existing prompt format and expect Gemini
        # to use the tool based on the prompt's instructions.
        _LOGGER.info(f"Full prompt for Gemini API: {full_prompt}")
        # entity_data_json is part of the full_prompt, so not logging separately unless needed for specific debugging.
        _LOGGER.debug(f"Sending prompt to Gemini: {full_prompt[:500]}...") # Log truncated prompt

        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=full_prompt, # The prompt now includes the entity data as a string
                config=DEFAULT_GENERATION_CONFIG,
                safety_settings=DEFAULT_SAFETY_SETTINGS,
                tools=[INSIGHTS_TOOL]
            )

            _LOGGER.debug(f"Raw Gemini API response object: {response}")

            if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                _LOGGER.warning("Gemini response did not contain the expected content parts. Raw response: %s", response)
                return {"insights": "No content parts in response.", "alerts": "", "actions": "", "raw_text": str(response)}

            # In the new SDK, the function call is directly on the part if it's a function call.
            # The response structure might be slightly different.
            # We expect a function call part.
            # If automatic function calling was enabled (it's not explicitly here but is default for some cases),
            # the response might directly contain the result of the function if it were executed by the client.
            # However, we are expecting the LLM to return a function call that we then parse.

            # Iterate through parts to find the function call
            function_call_part = None
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    function_call_part = part.function_call
                    break
            
            if not function_call_part:
                _LOGGER.warning("Gemini response did not include a function call. It might have responded with text directly. Raw text: %s", response.text if hasattr(response, 'text') and response.text else "N/A")
                if hasattr(response, 'text') and response.text:
                    return {"insights": response.text, "alerts": "No function call; direct text response.", "actions": "", "raw_text": response.text}
                return {"insights": "No function call in response and no fallback text.", "alerts": "", "actions": "", "raw_text": str(response)}

            if function_call_part.name != "generate_insights":
                _LOGGER.warning(f"Gemini called an unexpected function: {function_call_part.name}. Raw response: {response}")
                return {"insights": f"Unexpected function call: {function_call_part.name}", "alerts": "", "actions": "", "raw_text": str(response)}

            # The arguments are already structured data (Python dict)
            structured_data = dict(function_call_part.args)
            structured_data["raw_text"] = str(response) # Storing the whole response object as string

            _LOGGER.info(f"Successfully extracted structured data: {structured_data}")
            return structured_data

        except Exception as e:
            _LOGGER.error(f"Error calling Gemini API or processing its response: {e}")
            # Specific error handling for API key can be improved by catching specific google.api_core.exceptions
            if "API key not valid" in str(e) or "PermissionDenied" in str(e): # More robust check
                _LOGGER.error("Invalid or unauthorized Gemini API Key.")
                # Consider raising a custom exception that the config flow can catch for re-authentication
            return None
