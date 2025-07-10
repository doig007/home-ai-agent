"""Client for interacting with the Google Gemini API."""
import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

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


class GeminiClient:
    """A client for the Google Gemini API."""

    def __init__(self, api_key: str):
        """Initialize the Gemini client."""
        if not api_key:
            raise ValueError("Gemini API key is required.")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name="gemini-2.5-flash", # Using flash for speed and cost
            generation_config=DEFAULT_GENERATION_CONFIG,
            safety_settings=DEFAULT_SAFETY_SETTINGS
        )
        _LOGGER.info("Gemini Client initialized with model gemini-2.5-flash")

    def get_insights(self, prompt: str, entity_data_json: str) -> dict | None:

        """
        Get insights from the Gemini API based on the provided prompt and entity data.

        Args:
            prompt: The base prompt template.
            entity_data_json: A JSON string of the Home Assistant entity data.

        Returns:
            A dictionary containing the parsed insights, alerts, and summary,
            or None if an error occurs.
        """
        full_prompt = prompt.format(entity_data=entity_data_json)
        _LOGGER.info(f"Full prompt for Gemini API: {full_prompt}")
        _LOGGER.info(f"Entity data for Gemini API: {entity_data_json}")
        _LOGGER.debug(f"Sending prompt to Gemini: {full_prompt[:500]}...") # Log truncated prompt

        try:
            # Using async version if available, otherwise run in executor
            # For now, google.generativeai doesn't have a native async client for chat.
            # We will run the synchronous call in an executor.
            # response = await self._model.generate_content_async(full_prompt) # Not available yet

            # This is a synchronous call, so it should be run in an executor
            # to avoid blocking the Home Assistant event loop.
            # The DataUpdateCoordinator handles this by running its update_method
            # in an executor if it's not a coroutine.
            response = self._model.generate_content(full_prompt)

            _LOGGER.debug(f"Raw Gemini API response: {response.text[:500]}...") # Log truncated response

            # Basic parsing attempt. This will need to be made more robust.
            # The ideal way is to ask Gemini to return a JSON object.
            # For now, we'll assume the text is structured as requested.
            lines = response.text.strip().split('\n')
            insights_data = {"insights": "", "alerts": "", "summary": ""}
            current_section = None

            for line in lines:
                line_lower = line.lower()
                if "1. general insights" in line_lower or "general insights:" in line_lower :
                    current_section = "insights"
                    insights_data[current_section] += line.split(":", 1)[-1].strip() + " "
                elif "2. alerts" in line_lower or "alerts:" in line_lower:
                    current_section = "alerts"
                    insights_data[current_section] += line.split(":", 1)[-1].strip() + " "
                elif "3. summary" in line_lower or "summary:" in line_lower:
                    current_section = "summary"
                    insights_data[current_section] += line.split(":", 1)[-1].strip() + " "
                elif current_section:
                    insights_data[current_section] += line.strip() + " "

            # Trim whitespace
            for key in insights_data:
                insights_data[key] = insights_data[key].strip()

            if not insights_data["insights"] and not insights_data["alerts"] and not insights_data["summary"]:
                 _LOGGER.warning("Gemini response was empty or not parsable by simple splitting. Raw text: %s", response.text)
                 # Fallback to using the full text if parsing fails
                return {"insights": response.text, "alerts": "Could not parse.", "summary": "Could not parse.", "raw_text": response.text}

            # Include raw_text in the successful response
            insights_data["raw_text"] = response.text
            return insights_data

        except Exception as e:
            _LOGGER.error(f"Error calling Gemini API: {e}")
            # Check for specific API errors if possible by inspecting 'e'
            # For example, if hasattr(e, 'details'): _LOGGER.error(f"API Error details: {e.details}")
            if "API key not valid" in str(e): # Simple check
                # Potentially raise a specific exception or return an error code
                # that the coordinator can use to trigger a reauth flow or notify the user.
                _LOGGER.error("Invalid Gemini API Key.")
            return None
