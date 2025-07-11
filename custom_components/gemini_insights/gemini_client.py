"""Client for interacting with the Google Gemini API."""
import logging
from google import genai
from google.genai import types as genai_types # Alias to avoid conflict with local 'types'

from .const import CONF_API_KEY

_LOGGER = logging.getLogger(__name__)

# Safety settings to block harmful content. Adjust as needed.
# Refer to https://ai.google.dev/gemini-api/docs/safety-settings
DEFAULT_SAFETY_SETTINGS = [
    genai_types.SafetySetting(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
    genai_types.SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
    genai_types.SafetySetting(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
    genai_types.SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_MEDIUM_AND_ABOVE",
    ),
]

# Generation configuration for the model
# Refer to https://ai.google.dev/gemini-api/docs/config
BASE_GENERATION_CONFIG_PARAMS = {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 64000, # Adjust as needed, up to model limits
}

# Define the schema for the structured response
# For google.genai, Schema types are string literals like 'OBJECT', 'STRING'
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

# Define the tool for Gemini
INSIGHTS_TOOL = genai_types.Tool(
    function_declarations=[GENERATE_INSIGHTS_FUNCTION_DECLARATION]
)

class GeminiClient:
    """A client for the Google Gemini API."""

    def __init__(self, api_key: str):
        """Initialize the Gemini client."""
        if not api_key:
            raise ValueError("Gemini API key is required.")
        
        # Configure the genai library with the API key, standard for google-genai 1.7.0
        genai.configure(api_key=api_key)
        self._model_name = "gemini-1.5-flash" # Ensure this model is compatible with the new SDK version
        # Initialize the GenerativeModel
        self._model = genai.GenerativeModel(self._model_name)
        _LOGGER.info(f"Gemini Client initialized for model {self._model_name} using genai.configure() and GenerativeModel.")

    def get_insights(self, prompt: str, entity_data_json: str) -> dict | None:
        """
        Get insights from the Gemini API based on the provided prompt and entity data.
        The response will be structured according to the schema in GENERATE_INSIGHTS_FUNCTION_DECLARATION.

        Args:
            prompt: The base prompt template.
            entity_data_json: A JSON string of the Home Assistant entity data.

        Returns:
            A dictionary with "insights", "alerts", "actions", and "raw_text"
            or None if an error occurs.
        """
        full_prompt = prompt.format(entity_data=entity_data_json)
        _LOGGER.info(f"Full prompt for Gemini API: {full_prompt}")
        _LOGGER.debug(f"Sending prompt to Gemini: {full_prompt[:500]}...")

        # Construct the GenerationConfig object directly.
        gen_config_obj = genai_types.GenerationConfig(
            **BASE_GENERATION_CONFIG_PARAMS
            # response_mime_type="application/json" # This would go here if needed
        )

        try:
            # Call generate_content on the GenerativeModel instance, passing arguments directly.
            # This aligns with google-genai==1.7.0 SDK practices.
            response = self._model.generate_content(
                contents=full_prompt,
                generation_config=gen_config_obj,
                safety_settings=DEFAULT_SAFETY_SETTINGS,
                tools=[INSIGHTS_TOOL]
            )

            _LOGGER.debug(f"Raw Gemini API response object: {response}")

            if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
                _LOGGER.warning("Gemini response did not contain the expected content parts. Raw response: %s", response)
                return {"insights": "No content parts in response.", "alerts": "", "actions": "", "raw_text": str(response)}

            # Iterate through parts to find the function call
            function_call = None
            # The new SDK might structure parts differently, check response.text for direct text.
            # Function calls are typically in `response.candidates[0].content.parts[0].function_call`
            
            # According to new SDK, function_call is on the part.
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    function_call = part.function_call
                    break
            
            if not function_call:
                _LOGGER.warning("Gemini response did not include a function call. Text response: %s", response.text if response.text else "N/A")
                if response.text:
                    return {"insights": response.text, "alerts": "No function call; direct text response.", "actions": "", "raw_text": response.text}
                return {"insights": "No function call in response and no fallback text.", "alerts": "", "actions": "", "raw_text": str(response)}

            if function_call.name != "generate_insights":
                _LOGGER.warning(f"Gemini called an unexpected function: {function_call.name}. Raw response: {response}")
                return {"insights": f"Unexpected function call: {function_call.name}", "alerts": "", "actions": "", "raw_text": str(response)}

            # The arguments are already structured data (Python dict like object)
            # Convert to dict for consistent handling if it's not already.
            structured_data = dict(function_call.args)
            structured_data["raw_text"] = response.text # Store the textual part of the response.
                                                      # Or str(response) for the whole object if needed for debug.

            _LOGGER.info(f"Successfully extracted structured data: {structured_data}")
            return structured_data

        except Exception as e:
            _LOGGER.error(f"Error calling Gemini API or processing its response: {e}")
            # Check for specific API key errors if possible (e.g., based on error message or type)
            # from google.api_core import exceptions as google_exceptions
            # if isinstance(e, google_exceptions.PermissionDenied) or "API_KEY_INVALID" in str(e).upper():
            #    _LOGGER.error("Invalid or unauthorized Gemini API Key.")
            if "API key not valid" in str(e) or "PermissionDenied" in str(e) or "API_KEY_INVALID" in str(e).upper():
                 _LOGGER.error("Invalid or unauthorized Gemini API Key.")
            return None
