"""Constants for the Trixel contribution client integration."""

from typing import Final

from trixelserviceclient.schema import MeasurementType

from homeassistant.components.sensor.const import SensorDeviceClass

DOMAIN: Final = "trixel_contribution_client"

STORAGE_KEY_CONFIG: Final = "trixel_contribution_client_config"
STORAGE_VERSION_CONFIG: Final = 1

CONTRIBUTION_CLIENT: Final = "Trixel contribution client"
CONF_TLS_HOST: Final = "trixel_lookup_service_host"
CONF_TLS_USE_HTTPS: Final = "tls_use_https"
CONF_TMS_USE_HTTPS: Final = "tms_use_https"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_K_REQUIREMENT: Final = "k_privacy"
CONF_MAX_TRIXEL_DEPTH: Final = "maximum_trixel_depth"
CONF_OUTDOOR_TEMPERATURE_SENSORS: Final = "outdoor_temperature_sensors"
CONF_OUTDOOR_RELATIVE_HUMIDITY_SENSORS: Final = "outdoor_relative_humidity_sensors"
CONF_CONF_UPDATED: Final = "configuration_updated"

# Source (location fetching): met-component homeassistant/components/met/
DEFAULT_HOME_LATITUDE = 52.3731339
DEFAULT_HOME_LONGITUDE = 4.8903147


MEASUREMENT_TYPE_MAPPING: Final[dict[MeasurementType, str]] = {
    MeasurementType.AMBIENT_TEMPERATURE: CONF_OUTDOOR_TEMPERATURE_SENSORS,
    MeasurementType.RELATIVE_HUMIDITY: CONF_OUTDOOR_RELATIVE_HUMIDITY_SENSORS,
}

MEASUREMENT_TYPE_DEVICE_CLASS_MAPPING: Final[dict[MeasurementType, str]] = {
    MeasurementType.AMBIENT_TEMPERATURE: SensorDeviceClass.TEMPERATURE,
    MeasurementType.RELATIVE_HUMIDITY: SensorDeviceClass.HUMIDITY,
}
