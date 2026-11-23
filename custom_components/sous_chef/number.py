"""A probe's target, Pull early by and alarm limits, and an ambient sensor's target and alarm limits.

An alarm limit of 0 is no limit, and an ambient target of 0 is no target;
both show as unknown.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SousChefConfigEntry
from .const import DOMAIN
from .entity import AmbientEntity, ProbeEntity

# The largest value of each kind of number, in °F and in °C
PROBE_MAX = {UnitOfTemperature.FAHRENHEIT: 250, UnitOfTemperature.CELSIUS: 120}
AMBIENT_MAX = {UnitOfTemperature.FAHRENHEIT: 1000, UnitOfTemperature.CELSIUS: 540}
PULL_EARLY_MAX = {UnitOfTemperature.FAHRENHEIT: 30, UnitOfTemperature.CELSIUS: 15}
# A grill's target: its range and step, in °F and in °C
GRILL_MIN = {UnitOfTemperature.FAHRENHEIT: 100, UnitOfTemperature.CELSIUS: 40}
GRILL_MAX = {UnitOfTemperature.FAHRENHEIT: 700, UnitOfTemperature.CELSIUS: 370}
GRILL_STEP = {UnitOfTemperature.FAHRENHEIT: 5, UnitOfTemperature.CELSIUS: 1}


async def async_setup_entry(
    hass: HomeAssistant, entry: SousChefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry_id, probe in entry.runtime_data.probes.items():
        subentry = entry.subentries[subentry_id]
        async_add_entities(
            [
                TargetNumber(hass, subentry, probe, "target"),
                PullEarlyNumber(hass, subentry, probe, "pull_early"),
                ProbeLimitNumber(hass, subentry, probe, "alarm_high"),
                ProbeLimitNumber(hass, subentry, probe, "alarm_low"),
            ],
            config_subentry_id=subentry_id,
        )
    for subentry_id, ambient in entry.runtime_data.ambients.items():
        subentry = entry.subentries[subentry_id]
        async_add_entities(
            [
                GrillTargetNumber(hass, subentry, ambient, "target"),
                AmbientLimitNumber(hass, subentry, ambient, "alarm_high"),
                AmbientLimitNumber(hass, subentry, ambient, "alarm_low"),
            ],
            config_subentry_id=subentry_id,
        )


class TemperatureNumber(NumberEntity):
    """A temperature setting, in its sensor's unit."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _maximum: dict[str, float] = PROBE_MAX

    @property
    def unit(self) -> str:
        raise NotImplementedError

    @property
    def native_unit_of_measurement(self) -> str:
        return self.unit

    @property
    def native_max_value(self) -> float:
        return self._maximum.get(self.unit, self._maximum[UnitOfTemperature.CELSIUS])


class TargetNumber(ProbeEntity, TemperatureNumber):
    """The temperature the probe's internal temperature is cooking to.

    Choosing a doneness sets it; setting it to any other value makes the
    doneness Custom.
    """

    @property
    def unit(self) -> str:
        return self.probe.unit

    @property
    def native_min_value(self) -> float:
        return 32 if self.unit == UnitOfTemperature.FAHRENHEIT else 0

    @property
    def native_value(self) -> float | None:
        return self.probe.target

    async def async_set_native_value(self, value: float) -> None:
        self.probe.set_target(value)


class PullEarlyNumber(ProbeEntity, NumberEntity):
    """Done turns on this many degrees before the target, for carryover while the food rests.

    A difference of degrees, so it has no temperature device class: Home
    Assistant would convert it as a temperature.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_min_value = 0

    @property
    def native_unit_of_measurement(self) -> str:
        return self.probe.unit

    @property
    def native_max_value(self) -> float:
        return PULL_EARLY_MAX.get(self.probe.unit, PULL_EARLY_MAX[UnitOfTemperature.CELSIUS])

    @property
    def native_value(self) -> float:
        return self.probe.pull_early

    async def async_set_native_value(self, value: float) -> None:
        self.probe.set_pull_early(value)


class LimitNumber(TemperatureNumber):
    """An alarm limit. 0 is no limit."""

    _attr_native_min_value = 0

    @property
    def _high(self) -> bool:
        return self.translation_key == "alarm_high"


class ProbeLimitNumber(ProbeEntity, LimitNumber):
    """The internal temperature must stay below Alarm high and above Alarm low while the probe is on."""

    @property
    def unit(self) -> str:
        return self.probe.unit

    @property
    def native_value(self) -> float | None:
        return self.probe.limits.high if self._high else self.probe.limits.low

    async def async_set_native_value(self, value: float) -> None:
        self.probe.set_limit(self._high, value or None)


class AmbientLimitNumber(AmbientEntity, LimitNumber):
    """The ambient temperature must stay below Alarm high and above Alarm low."""

    _maximum = AMBIENT_MAX

    @property
    def unit(self) -> str:
        return self.ambient.unit

    @property
    def native_value(self) -> float | None:
        return self.ambient.limits.high if self._high else self.ambient.limits.low

    async def async_set_native_value(self, value: float) -> None:
        self.ambient.set_limit(self._high, value or None)


class GrillTargetNumber(AmbientEntity, TemperatureNumber):
    """The temperature the grill, pit or oven is held at. 0 is no target.

    Choosing a cook style sets it; setting it by hand makes the cook style
    Custom. Its state is recorded, so a dashboard can graph it beside the
    ambient reading.
    """

    _attr_native_min_value = 0
    _maximum = GRILL_MAX

    @property
    def unit(self) -> str:
        return self.ambient.unit

    @property
    def native_step(self) -> float:
        return GRILL_STEP.get(self.unit, GRILL_STEP[UnitOfTemperature.CELSIUS])

    @property
    def native_value(self) -> float | None:
        return self.ambient.target

    async def async_set_native_value(self, value: float) -> None:
        lowest = GRILL_MIN.get(self.unit, GRILL_MIN[UnitOfTemperature.CELSIUS])
        if 0 < value < lowest:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="grill_target_too_low",
                translation_placeholders={"lowest": f"{lowest} {self.unit}"},
            )
        self.ambient.set_target(value or None)
