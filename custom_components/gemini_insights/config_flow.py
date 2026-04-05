"""Config flow for Gemini Insights."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers import entity_registry, selector

from .const import (
    CONF_ACTION_CONFIDENCE_THRESHOLD,
    CONF_AUTO_EXECUTE_ACTIONS,
    CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
    CONF_ENABLE_LEARNING,
    CONF_ENTITIES,
    CONF_FORECAST_HOURS,
    CONF_HISTORY_PERIOD,
    CONF_MAX_CONFIRMATION_REQUESTS,
    CONF_MODEL,
    CONF_NOTIFICATION_SERVICE,
    CONF_PROMPT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_CONFIRMATION_NOTIFICATIONS,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_FORECAST_HOURS,
    DEFAULT_MAX_CONFIRMATION_REQUESTS,
    DEFAULT_HISTORY_PERIOD,
    DEFAULT_MODEL,
    DEFAULT_NOTIFICATION_SERVICE,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    HISTORY_12_HOURS,
    HISTORY_1_HOUR,
    HISTORY_24_HOURS,
    HISTORY_3_DAYS,
    HISTORY_6_HOURS,
    HISTORY_7_DAYS,
    HISTORY_LATEST_ONLY,
)

_LOGGER = logging.getLogger(__name__)


class GeminiInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gemini Insights."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            if not user_input.get(CONF_API_KEY):
                errors["base"] = "api_key_required"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_API_KEY][:10])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Gemini Insights", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Required(CONF_MODEL, default=DEFAULT_MODEL): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return GeminiInsightsOptionsFlowHandler()


class GeminiInsightsOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow using a direct entity picker."""

    async def async_step_init(self, user_input=None):
        """Manage options with a direct entity picker."""
        ent_reg = entity_registry.async_get(self.hass)
        enabled_entity_ids = sorted(
            entity.entity_id
            for entity in ent_reg.entities.values()
            if entity.disabled_by is None
        )

        if user_input is not None:
            user_input[CONF_ENTITIES] = sorted(user_input.get(CONF_ENTITIES, []))
            return self.async_create_entry(title="", data=user_input)

        current_config = self.config_entry.options
        current_entities = current_config.get(CONF_ENTITIES, [])
        valid_current_entities = [
            entity_id for entity_id in current_entities if entity_id in enabled_entity_ids
        ]

        schema = vol.Schema(
            {
                vol.Optional(CONF_ENTITIES, default=valid_current_entities): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        multiple=True,
                        include_entities=enabled_entity_ids,
                    )
                ),
                vol.Required(
                    CONF_MODEL,
                    default=self.config_entry.options.get(
                        CONF_MODEL,
                        self.config_entry.data.get(CONF_MODEL, DEFAULT_MODEL),
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(
                    CONF_PROMPT,
                    default=self.config_entry.options.get(
                        CONF_PROMPT,
                        self.config_entry.data.get(CONF_PROMPT, DEFAULT_PROMPT),
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True,
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_UPDATE_INTERVAL,
                        self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                vol.Required(
                    CONF_HISTORY_PERIOD,
                    default=self.config_entry.options.get(
                        CONF_HISTORY_PERIOD,
                        self.config_entry.data.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD),
                    ),
                ): vol.In(
                    [
                        HISTORY_LATEST_ONLY,
                        HISTORY_1_HOUR,
                        HISTORY_6_HOURS,
                        HISTORY_12_HOURS,
                        HISTORY_24_HOURS,
                        HISTORY_3_DAYS,
                        HISTORY_7_DAYS,
                    ]
                ),
                vol.Optional(
                    CONF_AUTO_EXECUTE_ACTIONS,
                    default=self.config_entry.options.get(CONF_AUTO_EXECUTE_ACTIONS, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ACTION_CONFIDENCE_THRESHOLD,
                    default=self.config_entry.options.get(CONF_ACTION_CONFIDENCE_THRESHOLD, 0.7),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_LEARNING,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_LEARNING,
                        DEFAULT_ENABLE_LEARNING,
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_FORECAST_HOURS,
                    default=self.config_entry.options.get(
                        CONF_FORECAST_HOURS,
                        DEFAULT_FORECAST_HOURS,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=24,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
                        DEFAULT_ENABLE_CONFIRMATION_NOTIFICATIONS,
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFICATION_SERVICE,
                    default=self.config_entry.options.get(
                        CONF_NOTIFICATION_SERVICE,
                        DEFAULT_NOTIFICATION_SERVICE,
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(
                    CONF_MAX_CONFIRMATION_REQUESTS,
                    default=self.config_entry.options.get(
                        CONF_MAX_CONFIRMATION_REQUESTS,
                        DEFAULT_MAX_CONFIRMATION_REQUESTS,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=3,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
