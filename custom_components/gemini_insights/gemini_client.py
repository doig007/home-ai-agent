"""Client for interacting with the Google Gemini API."""
import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, FunctionDeclaration, Tool, OpenAPISchema, Type

from .const import CONF_API_KEY

_LOGGER = logging.getLogger(__name__)

# Safety settings to block harmful content. Adjust as needed.
# Refer to https://ai.google.dev/docs/safety_setting_gemini
DEFAULT_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
}

# Generation configuration for the model
# Refer to https://ai.google.dev/docs/generation_config
DEFAULT_GENERATION_CONFIG = {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 64000, # Adjust as needed, up to model limits
}

# Define the schema for the structured response
RESPONSE_SCHEMA = OpenAPISchema(
    type=Type.OBJECT,
    properties={
        'insights': OpenAPISchema(type=Type.STRING, description="General insights derived from the data."),
        'alerts': OpenAPISchema(type=Type.STRING, description="Specific alerts or warnings based on the data."),
        'actions': OpenAPISchema(type=Type.STRING, description="Suggested actions or next steps."),
    },
    required=['insights', 'alerts', 'actions']
)

# Define the function declaration for Gemini
GENERATE_INSIGHTS_FUNCTION = FunctionDeclaration(
    name="generate_insights",
    description="Generates insights, alerts, and actions based on the provided data.",
    parameters=RESPONSE_SCHEMA,
)

# Define the tool for Gemini
INSIGHTS_TOOL = Tool(
    function_declarations=[GENERATE_INSIGHTS_FUNCTION]
)

class GeminiClient:
    """A client for the Google Gemini API."""

    def __init__(self, api_key: str):
        """Initialize the Gemini client."""
        if not api_key:
            raise ValueError("Gemini API key is required.")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config=DEFAULT_GENERATION_CONFIG,
            safety_settings=DEFAULT_SAFETY_SETTINGS,
            tools=[INSIGHTS_TOOL]
        )
        _LOGGER.info("Gemini Client initialized with model gemini-2.5-flash and insights tool")

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
        _LOGGER.info(f"Entity data for Gemini API: {entity_data_json}")
        _LOGGER.debug(f"Sending prompt to Gemini: {full_prompt[:500]}...") # Log truncated prompt

        try:
            # This is a synchronous call.
            response = self._model.generate_content(full_prompt)

            _LOGGER.debug(f"Raw Gemini API response object: {response}")
            
            # Extract the function call response
            if not response.candidates or not response.candidates[0].content.parts:
                _LOGGER.warning("Gemini response did not contain the expected content parts. Raw response: %s", response)
                return {"insights": "No content parts in response.", "alerts": "", "actions": "", "raw_text": str(response)}

            part = response.candidates[0].content.parts[0]
            if not hasattr(part, 'function_call'):
                _LOGGER.warning("Gemini response did not include a function call. It might have responded with text directly. Raw text: %s", response.text if hasattr(response, 'text') else "N/A")
                # Fallback: attempt to parse the text content if available
                if hasattr(response, 'text') and response.text:
                    return {"insights": response.text, "alerts": "No function call; direct text response.", "actions": "", "raw_text": response.text}
                return {"insights": "No function call in response and no fallback text.", "alerts": "", "actions": "", "raw_text": str(response)}

            function_call = part.function_call
            if function_call.name != "generate_insights":
                _LOGGER.warning(f"Gemini called an unexpected function: {function_call.name}. Raw response: {response}")
                return {"insights": f"Unexpected function call: {function_call.name}", "alerts": "", "actions": "", "raw_text": str(response)}

            # The arguments are already structured data (Python dict)
            structured_data = dict(function_call.args)

            # Add raw_text for debugging or other uses
            structured_data["raw_text"] = str(response) # Storing the whole response object as string

            _LOGGER.info(f"Successfully extracted structured data: {structured_data}")
            return structured_data

        except Exception as e:
            _LOGGER.error(f"Error calling Gemini API or processing its response: {e}")
            # Check for specific API errors if possible by inspecting 'e'
            # For example, if hasattr(e, 'details'): _LOGGER.error(f"API Error details: {e.details}")
            if "API key not valid" in str(e): # Simple check
                # Potentially raise a specific exception or return an error code
                # that the coordinator can use to trigger a reauth flow or notify the user.
                _LOGGER.error("Invalid Gemini API Key.")
            return None
