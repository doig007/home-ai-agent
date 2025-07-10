"""Constants for the Gemini Insights integration."""

DOMAIN = "gemini_insights"
CONF_API_KEY = "api_key"
CONF_PROMPT = "prompt"
CONF_ENTITIES = "entities"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_PROMPT = """
Analyze the following Home Assistant data and provide:
1. General insights based on useful observed trends.
2. Alerts if anything looks out of the ordinary.
3. A summary of the data for the specified entities.
Data:
{entity_data}
"""
DEFAULT_UPDATE_INTERVAL = 1800  # seconds (30 minutes)
