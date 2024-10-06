"""The Trixel contribution client integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from trixelserviceclient import ClientConfig
from trixelserviceclient.exception import BaseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.storage import Store

from .const import CONF_UPDATE_INTERVAL, STORAGE_KEY_CONFIG, STORAGE_VERSION_CONFIG
from .integration_polling_client import (
    IntegrationPollingClient,
    NoExistingConfigurationError,
    NoHomeError,
)

type TrixelContributionConfigEntry = ConfigEntry[ClientConfig]
_LOGGER = logging.getLogger(__name__)


async def done_callback(
    task: asyncio.Task, hass: HomeAssistant, entry: TrixelContributionConfigEntry
) -> None:
    """Reload this integration in hopes of recovering or reporting the error to the user."""
    if task.exception():
        client: IntegrationPollingClient = entry.runtime_data
        client.kill()

        hass.config_entries.async_schedule_reload(entry_id=entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: TrixelContributionConfigEntry
) -> bool:
    """Instantiate a Trixel contribution client (from storage) and update it with the current user configuration."""

    entry.runtime_data = await IntegrationPollingClient.create(
        hass=hass, data=entry.data, options=entry.options
    )
    client: IntegrationPollingClient = entry.runtime_data

    task = asyncio.create_task(
        client.run(
            polling_interval=timedelta(seconds=entry.options[CONF_UPDATE_INTERVAL])
        )
    )

    def done(task: asyncio.Task) -> None:
        hass.async_create_task(
            target=done_callback(task, hass, entry),
            name="Trixel contribution client done callback",
            eager_start=True,
        )

    # Wait and check if the client started successfully
    await asyncio.sleep(2.5)

    if task.done() and (exception := task.exception()):
        raise ConfigEntryNotReady from exception

    task.add_done_callback(done)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TrixelContributionConfigEntry
) -> bool:
    """Unload the config entry and persist the client configuration to storage."""
    client: IntegrationPollingClient = entry.runtime_data
    client.kill()
    return True


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove the config entry and attempt to gracefully remove the client from the network."""

    try:
        client = await IntegrationPollingClient.create(hass=hass)
        await client.run(delete=True)
        _LOGGER.info("Removed measurement station gracefully from TLS!")
    except (BaseError, NoHomeError, NoExistingConfigurationError):
        _LOGGER.warning("Failed to gracefully remove measurement station from TLS!")

    store = Store[dict](hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
    await store.async_remove()
