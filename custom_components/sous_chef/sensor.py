"""How a probe's cook is coming along (progress, rate, when it is done), and its hottest channel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SousChefConfigEntry
from .entity import ProbeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: SousChefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry_id, probe in entry.runtime_data.probes.items():
        subentry = entry.subentries[subentry_id]
        entities: list[SensorEntity] = [
            ProgressSensor(hass, subentry, probe, "progress"),
            RateSensor(hass, subentry, probe, "rate"),
            DoneAtSensor(hass, subentry, probe, "done_at"),
        ]
        # Only a probe with channels has a hottest one
        if probe.channels:
            entities.append(MaxSensor(hass, subentry, probe, "max"))
        async_add_entities(entities, config_subentry_id=subentry_id)


class ProgressSensor(ProbeEntity, SensorEntity):
    """How far the internal temperature has come from the cook's start to the target.

    Its attributes tell the Sous Chef Card which probe this is: its internal
    temperature (an entity ID, or empty for the lowest of the channels), its
    channels in order from the tip, its colors and the cook's start.
    """

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    # They describe the probe, not the cook, so the recorder leaves them out
    _unrecorded_attributes = frozenset({"internal", "channels", "colors", "start"})

    @property
    def native_value(self) -> float | None:
        return self.probe.progress

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "internal": self.probe.internal,
            "channels": self.probe.channels,
            "colors": self.probe.colors,
            "start": self.probe.start,
        }


class RateSensor(ProbeEntity, SensorEntity):
    """How fast the internal temperature is rising, in degrees per minute."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_unit_of_measurement(self) -> str:
        return f"{self.probe.unit}/min"

    @property
    def native_value(self) -> float | None:
        return None if (rate := self.probe.rate) is None else round(rate, 2)


class DoneAtSensor(ProbeEntity, SensorEntity):
    """When the internal temperature will reach the target, less Pull early by, at its current rate.

    Its projection attribute gives the readings Sous Chef expects on the way,
    so the Sous Chef Card draws them as they are worked out here.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # It changes with every reading, so the recorder leaves it out
    _unrecorded_attributes = frozenset({"projection"})

    @property
    def native_value(self) -> datetime | None:
        return self.probe.done_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "projection": [
                {"time": time.isoformat(), "temperature": round(temperature, 1)}
                for time, temperature in self.probe.projection
            ]
        }


class MaxSensor(ProbeEntity, SensorEntity):
    """The highest of the probe's channels right now, whichever it is."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self) -> str:
        return self.probe.unit

    @property
    def native_value(self) -> float | None:
        return self.probe.max
