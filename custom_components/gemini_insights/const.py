"""Constants for the Gemini Insights integration."""

DOMAIN = "gemini_insights"
CONF_API_KEY = "api_key"
CONF_PROMPT = "prompt"
CONF_ENTITIES = "entities"
CONF_DOMAINS = "domains"
CONF_AREAS   = "areas"
CONF_INCLUDE_PATTERNS = "include_patterns"
CONF_EXCLUDE_PATTERNS = "exclude_patterns"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_HISTORY_PERIOD = "history_period"
CONF_AUTO_EXECUTE_ACTIONS = "auto_execute_actions"
CONF_ACTION_CONFIDENCE_THRESHOLD = "action_confidence_threshold"

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

DEFAULT_UPDATE_INTERVAL = 1800  # seconds (30 minutes)

DEFAULT_PROMPT = """
Analyze the following Home Assistant data, which is provided as a JSON object.
Data:
{entity_data}

Based on the data, provide:
1. Concise insights about trends or patterns.
2. Alerts for any unusual or noteworthy activity.
3. Recommended Home Assistant service calls to execute, if applicable.

Here is the complete list of available Home Assistant services you can call. Use only these.
For each action, include your confidence as a decimal number between 0.0 and 1.0.
Action Schema:
{action_schema}

Respond in a brief JSON format with "insights", "alerts", and "to_execute" keys.
"""




