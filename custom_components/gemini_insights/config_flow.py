"""Config flow for Gemini Insights."""
import logging
import fnmatch
from typing import Any, Dict, List
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import selector, entity_registry, area_registry

from .const import (
    DOMAIN,
    CONF_PROMPT,
    CONF_ENTITIES,
    CONF_UPDATE_INTERVAL,
    CONF_DOMAINS,
    CONF_AREAS,
    CONF_INCLUDE_PATTERNS,
    CONF_EXCLUDE_PATTERNS,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    CONF_HISTORY_PERIOD,
    DEFAULT_HISTORY_PERIOD,
    CONF_AUTO_EXECUTE_ACTIONS,
    CONF_ACTION_CONFIDENCE_THRESHOLD,    
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
        return GeminiInsightsOptionsFlowHandler()

class GeminiInsightsOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow using domain/area check-boxes."""      

    async def async_step_init(self, user_input=None):
        """Manage options with category check-boxes."""
        errors = {}

        # Build dynamic domain list from registry
        ent_reg = entity_registry.async_get(self.hass)
        area_reg = area_registry.async_get(self.hass)

        # Pre-filter to get only enabled entities
        enabled_entities = [
            entity for entity in ent_reg.entities.values() if entity.disabled_by is None
        ]
        enabled_entity_ids = {entity.entity_id for entity in enabled_entities}

        domains = sorted({entity.domain for entity in enabled_entities})
        areas = sorted({
            area_reg.areas[entity.area_id].name
            for entity in enabled_entities
            if entity.area_id and entity.area_id in area_reg.areas
        })





        # Resolve selections → final entity list
        if user_input is not None:
            
            selected_entities = set()           
            selected_domains = user_input.get(CONF_DOMAINS, [])
            selected_areas = user_input.get(CONF_AREAS, [])

            for entity in enabled_entities:
                domain_ok = entity.domain in selected_domains
                
                area_name = None
                if entity.area_id and entity.area_id in area_reg.areas:
                    area_name = area_reg.areas[entity.area_id].name
                
                area_ok = area_name in selected_areas

                if domain_ok or area_ok:
                    selected_entities.add(entity.entity_id)
            
            # Add entries matching include patterns (now filters against enabled entities)
            include_patterns_str = user_input.get(CONF_INCLUDE_PATTERNS, "")
            if include_patterns_str:
                for pattern in [p.strip() for p in include_patterns_str.split(',') if p.strip()]:
                    selected_entities.update(fnmatch.filter(enabled_entity_ids, pattern))

            # Remove entities matching exclude patterns (supports wildcards)
            exclude_patterns_str = user_input.get(CONF_EXCLUDE_PATTERNS, "")
            if exclude_patterns_str:
                entities_to_remove = set()
                for pattern in [p.strip() for p in exclude_patterns_str.split(',') if p.strip()]:
                    entities_to_remove.update(fnmatch.filter(selected_entities, pattern))
                selected_entities -= entities_to_remove

            # Store the final sorted list in the user_input to be saved
            user_input[CONF_ENTITIES] = sorted(list(selected_entities))
            return self.async_create_entry(title="", data=user_input)

        # Current/previous values
        current_config = self.config_entry.options
        current_entities = current_config.get(CONF_ENTITIES, [])

        # Build the list of currently selected domains / areas safely
        ent_reg = entity_registry.async_get(self.hass)
        area_reg = area_registry.async_get(self.hass)

        current_domains = {e.split(".", 1)[0] for e in current_entities if e in ent_reg.entities}
        current_areas = {
            area_reg.areas.get(ent_reg.entities[e].area_id, {}).name
            for e in current_entities
            if e in ent_reg.entities and ent_reg.entities[e].area_id
        }

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DOMAINS,
                    default=list(current_domains)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=domains,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        custom_value=False
                    ),
                ),
                vol.Optional(
                    CONF_AREAS,
                    default=list(current_areas)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=areas,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        custom_value=False
                    ),
                ),
                vol.Optional(
                    CONF_INCLUDE_PATTERNS,
                    default=current_config.get(CONF_INCLUDE_PATTERNS, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    CONF_EXCLUDE_PATTERNS,
                    default=current_config.get(CONF_EXCLUDE_PATTERNS, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(
                    CONF_PROMPT,
                    default=self.config_entry.options.get(
                        CONF_PROMPT,
                        self.config_entry.data.get(CONF_PROMPT, DEFAULT_PROMPT)
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
                        self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                vol.Required(
                    CONF_HISTORY_PERIOD,
                    default=self.config_entry.options.get(
                        CONF_HISTORY_PERIOD,
                        self.config_entry.data.get(CONF_HISTORY_PERIOD, DEFAULT_HISTORY_PERIOD)
                    ),
                ): vol.In([
                    HISTORY_LATEST_ONLY,
                    HISTORY_1_HOUR,
                    HISTORY_6_HOURS,
                    HISTORY_12_HOURS,
                    HISTORY_24_HOURS,
                    HISTORY_3_DAYS,
                    HISTORY_7_DAYS,
                ]),
                vol.Optional(
                    CONF_AUTO_EXECUTE_ACTIONS,
                    default=self.config_entry.options.get(CONF_AUTO_EXECUTE_ACTIONS, False)
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ACTION_CONFIDENCE_THRESHOLD,
                    default=self.config_entry.options.get(CONF_ACTION_CONFIDENCE_THRESHOLD, 0.7)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)