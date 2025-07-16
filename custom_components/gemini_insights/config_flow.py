"""Config flow for Gemini Insights."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_PROMPT,
    CONF_ENTITIES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    CONF_HISTORY_PERIOD,
    DEFAULT_HISTORY_PERIOD,
    HISTORY_LATEST_ONLY,
    HISTORY_1_HOUR,
    HISTORY_6_HOURS,
    HISTORY_12_HOURS,
    HISTORY_24_HOURS,
    HISTORY_3_DAYS,
    HISTORY_7_DAYS,

)

# Import GeminiClient to test API key, but be careful with blocking calls
# from .gemini_client import GeminiClient

_LOGGER = logging.getLogger(__name__)


class GeminiInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gemini Insights."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Here you would ideally validate the API key by making a simple test call.
            # However, this needs to be done carefully to avoid blocking the event loop.
            # For now, we'll just check if it's provided.
            # A proper validation would involve `hass.async_add_executor_job`.
            if not user_input.get(CONF_API_KEY):
                errors["base"] = "api_key_required"
            # Test API Key (example - replace with actual validation)
            # try:
            #     client = await self.hass.async_add_executor_job(
            #         GeminiClient, user_input[CONF_API_KEY]
            #     )
            #     # A more thorough test would be to make a simple, non-billable call if possible
            #     # await self.hass.async_add_executor_job(client.some_test_call)
            # except Exception:
            #     _LOGGER.error("Gemini API key validation failed")
            #     errors["base"] = "invalid_api_key"


            if not errors:
                await self.async_set_unique_id(user_input[CONF_API_KEY][:10]) # Example unique ID
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Gemini Insights", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    # Optional fields during initial setup, can be configured in options
                    # vol.Optional(CONF_ENTITIES, default=[]): selector.EntitySelector(
                    #     selector.EntitySelectorConfig(multiple=True),
                    # ),
                    # vol.Optional(CONF_PROMPT, default=DEFAULT_PROMPT): str,
                    # vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return GeminiInsightsOptionsFlowHandler(config_entry)


class GeminiInsightsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Gemini Insights."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            # You could add validation for options here if needed
            return self.async_create_entry(title="", data=user_input)

        # Get current or default values
        current_api_key = self.config_entry.data.get(CONF_API_KEY, "") # Should not be changed here ideally
        current_entities = self.config_entry.options.get(
            CONF_ENTITIES, self.config_entry.data.get(CONF_ENTITIES, [])
        )
        current_prompt = self.config_entry.options.get(
            CONF_PROMPT, self.config_entry.data.get(CONF_PROMPT, DEFAULT_PROMPT)
        )
        current_update_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        current_history_period = self.config_entry.options.get(
            CONF_HISTORY_PERIOD, self.config_entry.data.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD)
        )

        history_period_options = [
            HISTORY_LATEST_ONLY,
            HISTORY_1_HOUR,
            HISTORY_6_HOURS,
            HISTORY_12_HOURS,
            HISTORY_24_HOURS,
            HISTORY_3_DAYS,
            HISTORY_7_DAYS,
        ]


        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENTITIES, default=current_entities
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        multiple=True,
                        filter={
                            "domain": [
                                "sensor",
                                "binary_sensor",
                                "switch",
                                "light",
                                "climate",
                                "weather",
                                "person",
                                "device_tracker"
                            ]
                        }
                    )
                ),
                vol.Required(
                    CONF_PROMPT, default=current_prompt
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True,
                        type=selector.TextSelectorType.TEXT,
                        suffix="Configure the prompt template for Gemini"
                    )
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=current_update_interval
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                vol.Required(
                    CONF_HISTORY_PERIOD, default=current_history_period
                ): vol.In(history_period_options),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
