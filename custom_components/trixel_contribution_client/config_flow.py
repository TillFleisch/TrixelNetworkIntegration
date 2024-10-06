"""Config flow for Trixel contribution client integration."""

from __future__ import annotations

import logging
from typing import Any

from trixelserviceclient.exception import AuthenticationError, BaseError
import voluptuous as vol

from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CONF_UPDATED,
    CONF_K_REQUIREMENT,
    CONF_MAX_TRIXEL_DEPTH,
    CONF_OUTDOOR_RELATIVE_HUMIDITY_SENSORS,
    CONF_OUTDOOR_TEMPERATURE_SENSORS,
    CONF_TLS_HOST,
    CONF_TLS_USE_HTTPS,
    CONF_TMS_USE_HTTPS,
    CONF_UPDATE_INTERVAL,
    CONTRIBUTION_CLIENT,
    DOMAIN,
    STORAGE_KEY_CONFIG,
    STORAGE_VERSION_CONFIG,
)
from .integration_polling_client import IntegrationPollingClient, NoHomeError

_LOGGER = logging.getLogger(__name__)

STEP_GENERAL_CONFIG_FIXED_SCHEMA = {
    vol.Required(CONF_TLS_HOST): str,
    vol.Required(CONF_TLS_USE_HTTPS, default=True): bool,
    vol.Required(CONF_TMS_USE_HTTPS, default=True): bool,
}


STEP_GENERAL_CONFIG_SCHEMA = {
    vol.Required(
        CONF_UPDATE_INTERVAL,
        default=60,
    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=900)),
    vol.Required(CONF_K_REQUIREMENT, default=3): vol.All(
        vol.Coerce(int), vol.Range(min=2)
    ),
    vol.Required(CONF_MAX_TRIXEL_DEPTH, default=24): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=24)
    ),
}


STEP_GENERAL_CONFIG_COMBINED_SCHEMA = vol.Schema(
    STEP_GENERAL_CONFIG_FIXED_SCHEMA
).extend(STEP_GENERAL_CONFIG_SCHEMA)

STEP_SELECT_SENSOR = vol.Schema(
    {
        vol.Required(CONF_OUTDOOR_TEMPERATURE_SENSORS): EntitySelector(
            EntitySelectorConfig(
                domain=Platform.SENSOR,
                device_class=SensorDeviceClass.TEMPERATURE,
                multiple=True,
            )
        ),
        vol.Required(CONF_OUTDOOR_RELATIVE_HUMIDITY_SENSORS): EntitySelector(
            EntitySelectorConfig(
                domain=Platform.SENSOR,
                device_class=SensorDeviceClass.HUMIDITY,
                multiple=True,
            )
        ),
    }
)


async def validate_connection(
    hass: HomeAssistant, data: dict[str, Any], options: dict[str, Any]
) -> None:
    """Validate that the user provided configuration can connect to/register at the provided network."""

    # Create a new client based on the provided config an attempt to register it at the network
    integration_client = await IntegrationPollingClient.create(
        hass=hass, data=data, options=options
    )

    # Try to register/start the contribution client to catch failures during setup
    await integration_client.start()
    integration_client.kill()


def validate_sensor_count(
    user_input: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Validate that the user provided sensor collection has at least size 1."""
    errors: dict[str, str] = {}

    sensor_count = sum(len(x) for x in user_input.values())
    if sensor_count == 0:
        errors["base"] = "not_enough_sensors"
        return errors
    return None


def retrieve_data_and_options(
    user_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retrieve the data and option part of the provided user configuration."""
    data_keys = {CONF_TLS_HOST, CONF_TLS_USE_HTTPS, CONF_TMS_USE_HTTPS}

    data = {key: user_config[key] for key in user_config.keys() & data_keys}
    options = {key: user_config[key] for key in user_config.keys() ^ data_keys}
    return data, options


class TrixelContributionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Trixel contribution client."""

    VERSION = 1

    def __init__(self) -> None:
        """Instantiate a new empty trixel contribution client flow."""
        self._user_config: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User triggered config flow step."""
        self._user_config = {}
        return await self.async_step_sensor_selection(user_input=user_input)

    async def async_step_sensor_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request and check contributing sensor selection."""

        if user_input is not None:
            if errors := validate_sensor_count(user_input=user_input):
                return self.async_show_form(
                    step_id="sensor_selection",
                    data_schema=STEP_SELECT_SENSOR,
                    errors=errors,
                )

            self._user_config.update(user_input)
            return await self.async_step_general_config()

        return self.async_show_form(
            step_id="sensor_selection",
            data_schema=STEP_SELECT_SENSOR,
        )

    async def async_step_general_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First time general configuration options which includes both data and options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Remove accidentally/old persisted configurations during aborted setup
            store = Store[dict](self.hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
            await store.async_remove()

            self._user_config.update(user_input)
            data, options = retrieve_data_and_options(self._user_config)

            try:
                await validate_connection(self.hass, data, options)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except NoHomeError:
                errors["base"] = "no_home"
            except BaseError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception(
                    "Unexpected exception during trixel contribution client stup"
                )
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=CONTRIBUTION_CLIENT, data=data, options=options
                )

        return self.async_show_form(
            step_id="general_config",
            data_schema=STEP_GENERAL_CONFIG_COMBINED_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """User requested reconfiguration step."""
        return await self.async_step_general_settings_reconfigure(user_input=user_input)

    async def async_step_general_settings_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ):
        """User requested re-configuration step for general options."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None:
            options = entry.options.copy()
            options.update(user_input)
            self._user_config = options

            return await self.async_step_sensor_selection_reconfigure()

        return self.async_show_form(
            step_id="general_settings_reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(STEP_GENERAL_CONFIG_SCHEMA), entry.options
            ),
        )

    async def async_step_sensor_selection_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request and handle changes to the user provided sensor selection."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            if errors := validate_sensor_count(user_input=user_input):
                return self.async_show_form(
                    step_id="sensor_selection_reconfigure",
                    data_schema=self.add_suggested_values_to_schema(
                        STEP_SELECT_SENSOR, entry.options
                    ),
                    errors=errors,
                )
            self._user_config.update(user_input)

            return self.async_update_reload_and_abort(
                entry=entry, options=self._user_config, reason=CONF_CONF_UPDATED
            )

        return self.async_show_form(
            step_id="sensor_selection_reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_SELECT_SENSOR, entry.options
            ),
        )
