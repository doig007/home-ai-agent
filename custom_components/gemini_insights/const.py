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
The following are Home Assistant data from specific entities within a family home. Analyse the trends and correlated events to provide:
1. Insights based on useful observed trends.  These should not be generic and should be specific to the latest day.
2. Alerts if anything looks unusual.
3. Recommended actions  to take.

Respond in an extremely concise way, suitable for a phone notification. Ignore any 'unknown' data points or data issues and don't comment on them.  Leave an element blank if no response of high value.

Data:
{entity_data}
"""
DEFAULT_UPDATE_INTERVAL = 1800  # seconds (30 minutes)
