"""Constants for the Gemini Insights integration."""

DOMAIN = "gemini_insights"
CONF_API_KEY = "api_key"
CONF_MODEL = "model"
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
CONF_ENABLE_LEARNING = "enable_learning"
CONF_ENABLE_CONFIRMATION_NOTIFICATIONS = "enable_confirmation_notifications"
CONF_NOTIFICATION_SERVICE = "notification_service"
CONF_FORECAST_HOURS = "forecast_hours"
CONF_MAX_CONFIRMATION_REQUESTS = "max_confirmation_requests"

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_ENABLE_LEARNING = True
DEFAULT_ENABLE_CONFIRMATION_NOTIFICATIONS = False
DEFAULT_NOTIFICATION_SERVICE = ""
DEFAULT_FORECAST_HOURS = 12
DEFAULT_MAX_CONFIRMATION_REQUESTS = 1

MOBILE_APP_NOTIFICATION_ACTION_EVENT = "mobile_app_notification_action"
SERVICE_RECORD_CONFIRMATION = "record_confirmation"
CONFIRMATION_CONFIRMED = "confirmed"
CONFIRMATION_REJECTED = "rejected"

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
You are analyzing Home Assistant data to learn how this household uses the home.
Only make claims that are grounded in the entity states. When you are uncertain, say so explicitly.

Home Assistant data:
{entity_data}

Entity context:
{entity_context}

Behavior summary:
{behavior_summary}

Persisted household learning:
{household_learning}

Recent confirmation outcomes:
{confirmation_history}

Forecast horizon in hours:
{forecast_hours}

Based on the data:
1. Explain the most likely household routines or occupancy-related patterns that show up in the entity states.
2. Provide a practical forecast for the next {forecast_hours} hours.
3. Raise alerts only for genuinely unusual or noteworthy activity.
4. Recommend Home Assistant service calls only when they are safe and clearly justified.
5. Propose up to 2 confirmation questions only when a short Home Assistant notification could materially improve future forecasts.

Here is the complete list of available Home Assistant services you can call. Use only these.
For each action, include your confidence as a decimal number between 0.0 and 1.0.
Action Schema:
{action_schema}

Return JSON with these keys:
- insights: brief household insight grounded in the data
- alerts: brief alert summary
- forecast: short forecast for the next {forecast_hours} hours
- to_execute: array of Home Assistant service calls
- learning_updates: array of learned patterns with pattern, status, confidence, evidence, and entities
- confirmation_requests: array of low-friction confirmation questions with question, pattern, reason, confidence, and entities
"""




