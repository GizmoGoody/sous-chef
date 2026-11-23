"""How a probe device's temperature sensors are laid out.

Most probe devices have one temperature sensor, and that sensor is the
internal temperature. A known probe is one whose layout is built in, so it
needs no questions: a ThermoWorks RFX MEAT reports its internal temperature
as channel 0 (the lowest of its four sensors) and its sensors as channels 1
to 4, with channel 1 at the tip.

A probe on its charger sends nothing, so a probe that stops reporting counts
as back on its charger once it has had no reading for the charger timeout.
An RFX probe's battery state is no help: ThermoWorks Cloud keeps the one it
sent last, "discharging", while the probe sits on its charger.

A known device can also say how to tell that it is reporting. ThermoWorks
Cloud keeps showing a sensor's last value after it stops reporting (an RFX
probe on its charger, for example), so a ThermoWorks sensor is reporting only
while its last_seen time is recent. ThermoWorks alarm thresholds are
temperature sensors too; they are left out, as they read no temperature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

THERMOWORKS = "thermoworks_cloud"
# A ThermoWorks sensor that has sent nothing for this long is on its charger, or out of range
THERMOWORKS_STALE_AFTER = timedelta(minutes=5)
# A probe that has had no reading for this long is back on its charger
CHARGER_TIMEOUT = timedelta(minutes=5)
# A ThermoWorks reading already counts as none once it is THERMOWORKS_STALE_AFTER old
THERMOWORKS_CHARGER_TIMEOUT = timedelta(minutes=1)
# A ThermoWorks channel's temperature has the unique ID thermoworks_cloud-<serial>-<channel>.
# Its alarm thresholds are temperature sensors too, but add a suffix after the channel.
THERMOWORKS_CHANNEL = re.compile(r".+-(\d+)")


@dataclass(frozen=True)
class Layout:
    """A known probe's internal temperature, and its sensors in order from the tip."""

    internal: str
    channels: list[str]


@dataclass(frozen=True)
class Freshness:
    """How to tell a device's sensors are reporting: the attribute that holds when they last sent data, and how old it may be."""

    attribute: str
    stale_after: timedelta
    # How long with no reading means the probe is back on its charger
    charger_timeout: timedelta = CHARGER_TIMEOUT


def _reads_temperature(entry: er.RegistryEntry) -> bool:
    """A temperature sensor that reads a temperature, not a setting such as an alarm threshold."""
    if entry.domain != "sensor" or entry.disabled_by:
        return False
    if (entry.device_class or entry.original_device_class) != "temperature":
        return False
    if entry.platform == THERMOWORKS:
        return THERMOWORKS_CHANNEL.fullmatch(entry.unique_id) is not None
    return True


def temperature_sensors(hass: HomeAssistant, device_id: str) -> list[str]:
    """The enabled sensors on a device that read a temperature."""
    return sorted(
        entry.entity_id
        for entry in er.async_entries_for_device(er.async_get(hass), device_id)
        if _reads_temperature(entry)
    )


def _manufacturer_model(hass: HomeAssistant, device_id: str) -> tuple[str, str] | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    return (device.manufacturer or "").lower(), (device.model or "").lower()


def freshness(hass: HomeAssistant, device_id: str) -> Freshness | None:
    """How to tell a known device's sensors are reporting, or None to trust every value.

    ThermoWorks Cloud keeps showing a sensor's last value after it stops
    reporting, so a ThermoWorks sensor counts only while its last_seen time
    is recent.
    """
    known = _manufacturer_model(hass, device_id)
    if known and known[0] == "thermoworks":
        return Freshness("last_seen", THERMOWORKS_STALE_AFTER, THERMOWORKS_CHARGER_TIMEOUT)
    return None


def known_layout(hass: HomeAssistant, device_id: str) -> Layout | None:
    """The built-in layout of a known probe, or None for any other device."""
    if _manufacturer_model(hass, device_id) == ("thermoworks", "rfx meat"):
        return _rfx_meat(hass, device_id)
    return None


def _rfx_meat(hass: HomeAssistant, device_id: str) -> Layout | None:
    channels: dict[int, str] = {}
    for entry in er.async_entries_for_device(er.async_get(hass), device_id):
        if _reads_temperature(entry) and (match := THERMOWORKS_CHANNEL.fullmatch(entry.unique_id)):
            channels[int(match.group(1))] = entry.entity_id
    if 0 not in channels:
        return None
    return Layout(internal=channels[0], channels=[channels[n] for n in (1, 2, 3, 4) if n in channels])
