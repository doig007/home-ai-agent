"""Constants for the Gemini Insights integration."""

DOMAIN = "gemini_insights"
CONF_API_KEY = "api_key"
CONF_PROMPT = "prompt"
CONF_ENTITIES = "entities"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_HISTORY_PERIOD = "history_period"

# History period options
HISTORY_LATEST_ONLY = "latest_only"
HISTORY_1_HOUR = "1_hour"
HISTORY_6_HOURS = "6_hours"
HISTORY_12_HOURS = "12_hours"
HISTORY_24_HOURS = "24_hours"
HISTORY_3_DAYS = "3_days"
HISTORY_7_DAYS = "7_days"

DEFAULT_HISTORY_PERIOD = HISTORY_LATEST_ONLY

# Map an option string to a timedelta object or a special value
HISTORY_PERIOD_TIMEDELTA_MAP = {
    # HISTORY_LATEST_ONLY is handled separately
    HISTORY_1_HOUR: {"hours": 1},
    HISTORY_6_HOURS: {"hours": 6},
    HISTORY_12_HOURS: {"hours": 12},
    HISTORY_24_HOURS: {"days": 1},
    HISTORY_3_DAYS: {"days": 3},
    HISTORY_7_DAYS: {"days": 7},
}


DEFAULT_PROMPT = """
Analyze the following Home Assistant data and provide:
1. General insights based on useful observed trends.
2. Alerts if anything looks out of the ordinary.
3. A summary of the data for the specified entities.
Data:
{entity_data}
"""
DEFAULT_UPDATE_INTERVAL = 1800  # seconds (30 minutes)
