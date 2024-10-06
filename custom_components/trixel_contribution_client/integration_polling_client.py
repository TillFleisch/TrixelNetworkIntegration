"""Client implementations which persist configuration changes with the Home Assistant storage helper."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Self

from trixelserviceclient.extended_clients.polling_client import PollingClient
from trixelserviceclient.schema import (
    ClientConfig,
    Coordinate,
    MeasurementStationConfig,
    MeasurementType,
    Sensor,
)

from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_K_REQUIREMENT,
    CONF_MAX_TRIXEL_DEPTH,
    CONF_TLS_HOST,
    DEFAULT_HOME_LATITUDE,
    DEFAULT_HOME_LONGITUDE,
    MEASUREMENT_TYPE_DEVICE_CLASS_MAPPING,
    MEASUREMENT_TYPE_MAPPING,
    STORAGE_KEY_CONFIG,
    STORAGE_VERSION_CONFIG,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class AnnotatedSensor(Sensor):
    """Annotated sensor which can be used to link a sensor to an existing entity id."""

    entity_id: str | None = None


async def load_client_config(hass: HomeAssistant) -> ClientConfig:
    """Load the trixel client config form persistent storage."""
    store = Store[dict](hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
    config_dict = await store.async_load()
    if config_dict is None:
        raise FileNotFoundError(
            "Helper storage does not contain a client configuration!"
        )

    # Convert stored configuration dictionary into typed configuration
    client_config: ClientConfig = ClientConfig(**config_dict)
    client_config.location = Coordinate(**client_config.location)
    client_config.ms_config = MeasurementStationConfig(**client_config.ms_config)
    client_config.sensors = [
        AnnotatedSensor(**sensor_config) for sensor_config in client_config.sensors
    ]
    for sensor in client_config.sensors:
        sensor.measurement_type = MeasurementType(sensor.measurement_type)

    return client_config


class IntegrationPollingClient(PollingClient):
    """A client implementation which persists the configuration with Home Assistants helper Storage."""

    hass: HomeAssistant
    _last_timestamps: dict[int, int]

    def __init__(self, hass: HomeAssistant, config: ClientConfig | None = None) -> None:
        """Instantiate a IntegrationPollingClient based on the provided configuration.

        :param hass: Home Assistant reference object
        :param config: client configuration which is used in case no pickle file is found or when override is enabled
        """
        self.hass = hass
        self._last_timestamps: dict[int, int] = {}
        super().__init__(config, None)

    @classmethod
    async def create(
        cls,
        hass: HomeAssistant,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> Self:
        """Create a client from persistent storage and apply the provided configuration updates."""

        # Source (location fetching): met-component homeassistant/components/met/
        # Don't create entry if latitude or longitude isn't set.
        # Also, filters out our onboarding default location.
        if (not hass.config.latitude and not hass.config.longitude) or (
            hass.config.latitude == DEFAULT_HOME_LATITUDE
            and hass.config.longitude == DEFAULT_HOME_LONGITUDE
        ):
            # TODO: add listener for latitude/longitude and update client config on change
            raise NoHomeError

        client_config: ClientConfig
        try:
            # Load an existing config (probably with token/uuid) and update according to the user configuration
            client_config = await load_client_config(hass=hass)

            client_config.location = Coordinate(
                latitude=hass.config.latitude, longitude=hass.config.longitude
            )
            if options is not None:
                client_config.k = options[CONF_K_REQUIREMENT]
                client_config.max_depth = options[CONF_MAX_TRIXEL_DEPTH]

                # Find differences between the new and an existing user configuration
                orphaned_sensors: list[AnnotatedSensor] = []
                new_sensors: list[tuple[MeasurementType, str]] = []
                for measurement_type in MeasurementType:
                    sensor: AnnotatedSensor
                    entity_ids = options[MEASUREMENT_TYPE_MAPPING.get(measurement_type)]
                    for entity_id in entity_ids:
                        entity_used: bool = False
                        for sensor in client_config.sensors:
                            if (
                                sensor.measurement_type == measurement_type
                                and sensor.entity_id == entity_id
                            ):
                                entity_used = True
                        if not entity_used:
                            new_sensors.append((measurement_type, entity_id))

                    orphaned_sensors.extend(
                        [
                            sensor
                            if sensor.measurement_type == measurement_type
                            and sensor.entity_id not in entity_ids
                            else None
                            for sensor in client_config.sensors
                        ]
                    )

                # Remove orphaned user configuration sensors from the client config such that they are later removed
                # from the TMS
                for sensor in orphaned_sensors:
                    if sensor is not None:
                        client_config.sensors.remove(sensor)

                # Add new sensors using a basic configuration
                for measurement_type, entity_id in new_sensors:
                    # TODO: add detail (sensor name and accuracy) to sensor object
                    client_config.sensors.append(
                        AnnotatedSensor(
                            measurement_type=measurement_type, entity_id=entity_id
                        )
                    )

        except FileNotFoundError as e:
            if data is None or options is None:
                raise NoExistingConfigurationError from e

            # Instantiate a fresh configuration which is not yet registered at the TMS
            sensors: list[AnnotatedSensor] = []
            for measurement_type, conf_value in MEASUREMENT_TYPE_MAPPING.items():
                sensors.extend(
                    [
                        AnnotatedSensor(
                            measurement_type=measurement_type, entity_id=entity
                        )
                        for entity in options[conf_value]
                    ]
                )
                # TODO: add detail (sensor name and accuracy) to sensor object

            client_config = ClientConfig(
                location=Coordinate(
                    latitude=hass.config.latitude, longitude=hass.config.longitude
                ),
                tls_host=data[CONF_TLS_HOST],
                k=options[CONF_K_REQUIREMENT],
                max_depth=options[CONF_MAX_TRIXEL_DEPTH],
                sensors=sensors,
            )

        return cls(hass=hass, config=client_config)

    async def _persist_config(self):
        """Persist the clients configuration in the helper storage."""
        store = Store[dict](self.hass, STORAGE_VERSION_CONFIG, STORAGE_KEY_CONFIG)
        await store.async_save(asdict(self._config))

    def _get_updates(
        self,
    ) -> dict[int, tuple[datetime, float]]:
        """Get the related entity states and returns them for publishing to the TMS."""

        updates: dict[int, tuple[datetime, float]] = {}

        sensor: AnnotatedSensor
        for sensor in self.sensors:
            state: State | None = self.hass.states.get(sensor.entity_id)

            if state is None:
                _LOGGER.warning(
                    "Entity %s cannot contribute as it's state could not be retrieved!",
                    sensor.entity_id,
                )
                continue

            value = None if state.state in ("unavailable", "unknown") else state.state

            if (
                state.attributes[ATTR_DEVICE_CLASS]
                != MEASUREMENT_TYPE_DEVICE_CLASS_MAPPING[sensor.measurement_type]
            ):
                # TODO: raise user - visible warning
                _LOGGER.warning(
                    "Entity %s cannot contribute with wrong device class!",
                    sensor.entity_id,
                )
                continue
            if (
                sensor.measurement_type == MeasurementType.AMBIENT_TEMPERATURE
                and state.attributes[ATTR_UNIT_OF_MEASUREMENT] not in UnitOfTemperature
            ):
                # TODO: raise user - visible warning
                _LOGGER.warning(
                    "Entity %s cannot contribute with wrong unit of measurement!",
                    sensor.entity_id,
                )
                continue

            # Convert units to standard used in the network
            if (
                state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.TEMPERATURE
                and value is not None
            ):
                value = TemperatureConverter.convert(
                    value,
                    state.attributes[ATTR_UNIT_OF_MEASUREMENT],
                    UnitOfTemperature.CELSIUS,
                )

            measurement_timestamp = int(
                round(state.last_reported.astimezone(UTC).timestamp())
            )
            # Ignore already transmitted measurements
            if measurement_timestamp != self._last_timestamps.get(sensor.sensor_id, 0):
                self._last_timestamps[sensor.sensor_id] = measurement_timestamp
                updates[sensor.sensor_id] = (
                    measurement_timestamp,
                    value,
                )

        return updates

    async def run(
        self,
        polling_interval: timedelta = timedelta(seconds=60),
        delete: bool = False,
    ):
        """Run this polling trixel service client."""
        return await super().run(
            get_updates=self._get_updates if delete is False else None,
            retry_interval=timedelta(seconds=30),
            max_retries=0,
            polling_interval=polling_interval,
            delete=delete,
        )


class NoHomeError(HomeAssistantError):
    """Missing user home location error."""


class NoExistingConfigurationError(HomeAssistantError):
    """Indicates that no existing client configuration could be found."""
