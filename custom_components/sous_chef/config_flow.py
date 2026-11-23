"""Set up Sous Chef, then add probes, ambient sensors and foods of your own."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    ObjectSelector,
    ObjectSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    COLORS,
    CONF_AUTO_OFF,
    CONF_AUTO_ON,
    CONF_CHANNELS,
    CONF_COLORS,
    CONF_DEVICE,
    CONF_ICON,
    CONF_INTERNAL,
    CONF_KEEP_LAST,
    CONF_LEVELS,
    CONF_NAME,
    CONF_SAFETY_FOOD,
    CONF_SENSOR,
    CONF_TEMPERATURE,
    CONF_UNIT,
    DOMAIN,
    SUBENTRY_AMBIENT,
    SUBENTRY_FOOD,
    SUBENTRY_PROBE,
)
from .presets import CUSTOM, FOODS, OTHER
from .profiles import known_layout, temperature_sensors

COLOR_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=COLORS, multiple=True, translation_key="color", mode=SelectSelectorMode.DROPDOWN)
)
TEMPERATURE_DEVICE = DeviceSelector(
    DeviceSelectorConfig(entity=[EntityFilterSelectorConfig(domain="sensor", device_class="temperature")])
)
LEVELS_SELECTOR = ObjectSelector(
    ObjectSelectorConfig(
        fields={
            CONF_NAME: {"selector": {"text": {}}, "required": True},
            CONF_TEMPERATURE: {"selector": {"number": {"mode": "box", "step": 1}}, "required": True},
        },
        multiple=True,
        label_field=CONF_NAME,
        description_field=CONF_TEMPERATURE,
        translation_key="levels",
    )
)


class SousChefConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry holds every probe, ambient sensor and food of your own."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SousChefOptionsFlow:
        return SousChefOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PROBE: ProbeSubentryFlow, SUBENTRY_AMBIENT: AmbientSubentryFlow, SUBENTRY_FOOD: FoodSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Sous Chef", data={}, options={CONF_KEEP_LAST: True})
        return self.async_show_form(step_id="user")


class SousChefOptionsFlow(OptionsFlow):
    """Whether a new cook keeps the last one's source, food and doneness."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_KEEP_LAST, default=True): BooleanSelector()}), self.config_entry.options
            ),
        )


def _device_name(hass: HomeAssistant, device_id: str) -> str:
    device = dr.async_get(hass).async_get(device_id)
    return (device.name_by_user or device.name or device_id) if device else device_id


def _entity_name(hass: HomeAssistant, entity_id: str) -> str:
    if state := hass.states.get(entity_id):
        return state.name
    entry = er.async_get(hass).async_get(entity_id)
    return (entry.name or entry.original_name or entity_id) if entry else entity_id


def _taken(subentry_flow: ConfigSubentryFlow, subentry_type: str, key: str) -> set[Any]:
    """What the entry's subentries of one type already use."""
    return {
        s.data.get(key) for s in subentry_flow._get_entry().subentries.values() if s.subentry_type == subentry_type
    }


def _sensors_schema(sensors: list[str], with_auto_on: bool) -> vol.Schema:
    """The internal temperature and the channels of a device with several temperature sensors."""
    fields: dict[Any, Any] = {
        vol.Optional(CONF_INTERNAL): EntitySelector(EntitySelectorConfig(include_entities=sensors)),
        vol.Optional(CONF_CHANNELS, default=[]): EntitySelector(
            EntitySelectorConfig(include_entities=sensors, multiple=True, reorder=True)
        ),
    }
    if with_auto_on:
        fields[vol.Required(CONF_AUTO_ON, default=True)] = BooleanSelector()
        fields[vol.Required(CONF_AUTO_OFF, default=True)] = BooleanSelector()
    return vol.Schema(fields)


def _sensors(user_input: dict[str, Any]) -> tuple[str | None, list[str], dict[str, str]]:
    """The internal temperature, the channels without it, and any error.

    An empty internal temperature is the lowest of the channels, so it needs
    two channels or more.
    """
    internal = user_input.get(CONF_INTERNAL) or None
    channels = [c for c in user_input.get(CONF_CHANNELS, []) if c != internal]
    if internal is None and len(channels) < 2:
        return None, channels, {CONF_INTERNAL: "no_internal"}
    return internal, channels, {}


class ProbeSubentryFlow(ConfigSubentryFlow):
    """A probe: its device and colors. Its sensors are found on the device."""

    def __init__(self) -> None:
        self._device: str | None = None
        self._colors: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device = user_input[CONF_DEVICE]
            colors = list(user_input.get(CONF_COLORS) or [])
            sensors = temperature_sensors(self.hass, device)
            if device in _taken(self, SUBENTRY_PROBE, CONF_DEVICE):
                errors[CONF_DEVICE] = "already_added"
            elif layout := known_layout(self.hass, device):
                return self._create(device, colors, layout.internal, layout.channels, auto_on=True, auto_off=True)
            elif len(sensors) == 1:
                return self._create(device, colors, sensors[0], [], auto_on=True, auto_off=True)
            elif not sensors:
                errors[CONF_DEVICE] = "no_temperature"
            else:
                self._device, self._colors = device, colors
                return await self.async_step_sensors()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE): TEMPERATURE_DEVICE,
                vol.Optional(CONF_COLORS, default=[]): COLOR_SELECTOR,
            }),
            errors=errors,
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """A device with several temperature sensors: its internal temperature, and its channels in order."""
        assert self._device is not None
        errors: dict[str, str] = {}
        sensors = temperature_sensors(self.hass, self._device)
        if user_input is not None:
            internal, channels, errors = _sensors(user_input)
            if not errors:
                return self._create(
                    self._device,
                    self._colors,
                    internal,
                    channels,
                    auto_on=user_input[CONF_AUTO_ON],
                    auto_off=user_input[CONF_AUTO_OFF],
                )
        schema = _sensors_schema(sensors, with_auto_on=True)
        return self.async_show_form(
            step_id="sensors",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            description_placeholders={"device": _device_name(self.hass, self._device)},
            errors=errors,
        )

    def _create(
        self,
        device: str,
        colors: list[str],
        internal: str | None,
        channels: list[str],
        auto_on: bool,
        auto_off: bool,
    ) -> SubentryFlowResult:
        return self.async_create_entry(
            title=_device_name(self.hass, device),
            data={
                CONF_DEVICE: device,
                CONF_INTERNAL: internal,
                CONF_CHANNELS: channels,
                CONF_COLORS: colors,
                CONF_AUTO_ON: auto_on,
                CONF_AUTO_OFF: auto_off,
            },
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        data = dict(subentry.data)
        device = data[CONF_DEVICE]
        sensors = temperature_sensors(self.hass, device)
        # The sensors of a known probe, or of a single sensor, are not asked
        choose_sensors = known_layout(self.hass, device) is None and len(sensors) > 1
        errors: dict[str, str] = {}
        if user_input is not None:
            data[CONF_COLORS] = list(user_input.get(CONF_COLORS) or [])
            data[CONF_AUTO_ON] = user_input[CONF_AUTO_ON]
            data[CONF_AUTO_OFF] = user_input[CONF_AUTO_OFF]
            if choose_sensors:
                data[CONF_INTERNAL], data[CONF_CHANNELS], errors = _sensors(user_input)
            if not errors:
                return self.async_update_and_abort(self._get_entry(), subentry, data=data)
        schema = vol.Schema({
            vol.Optional(CONF_COLORS, default=[]): COLOR_SELECTOR,
            vol.Required(CONF_AUTO_ON, default=True): BooleanSelector(),
            vol.Required(CONF_AUTO_OFF, default=True): BooleanSelector(),
        })
        if choose_sensors:
            schema = schema.extend(_sensors_schema(sensors, with_auto_on=False).schema)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or data),
            errors=errors,
        )


class AmbientSubentryFlow(ConfigSubentryFlow):
    """An ambient sensor: the air in a grill, pit or oven. Its device first, then its sensor if it has several."""

    def __init__(self) -> None:
        self._device: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device = user_input[CONF_DEVICE]
            sensors = [s for s in temperature_sensors(self.hass, device) if s not in _taken(self, SUBENTRY_AMBIENT, CONF_SENSOR)]
            if not temperature_sensors(self.hass, device):
                errors[CONF_DEVICE] = "no_temperature"
            elif not sensors:
                errors[CONF_DEVICE] = "already_added"
            elif len(sensors) == 1:
                return self._create(device, sensors[0])
            else:
                self._device = device
                return await self.async_step_sensor()
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_DEVICE): TEMPERATURE_DEVICE}), errors=errors
        )

    async def async_step_sensor(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """A device with several temperature sensors: which one reads the air."""
        assert self._device is not None
        if user_input is not None:
            return self._create(self._device, user_input[CONF_SENSOR])
        taken = _taken(self, SUBENTRY_AMBIENT, CONF_SENSOR)
        sensors = [s for s in temperature_sensors(self.hass, self._device) if s not in taken]
        return self.async_show_form(
            step_id="sensor",
            data_schema=vol.Schema({vol.Required(CONF_SENSOR): EntitySelector(EntitySelectorConfig(include_entities=sensors))}),
            description_placeholders={"device": _device_name(self.hass, self._device)},
        )

    def _create(self, device: str, sensor: str) -> SubentryFlowResult:
        return self.async_create_entry(
            title=_entity_name(self.hass, sensor), data={CONF_DEVICE: device, CONF_SENSOR: sensor}
        )


SAFETY_FOOD_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=FOODS, translation_key="safety_food", mode=SelectSelectorMode.DROPDOWN)
)


def _food_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_NAME): TextSelector(),
        vol.Optional(CONF_ICON): IconSelector(),
        vol.Optional(CONF_LEVELS, default=[]): LEVELS_SELECTOR,
        vol.Optional(CONF_SAFETY_FOOD): SAFETY_FOOD_SELECTOR,
    })


def _food_errors(user_input: dict[str, Any], taken: set[Any]) -> dict[str, str]:
    name = user_input[CONF_NAME].strip()
    if name in taken or name in FOODS or name.lower() in (OTHER, CUSTOM):
        return {CONF_NAME: "name_taken"}
    levels = [str(level.get(CONF_NAME, "")).strip() for level in user_input.get(CONF_LEVELS, [])]
    if any(not level or level.lower() == CUSTOM for level in levels) or len(set(levels)) != len(levels):
        return {CONF_LEVELS: "bad_levels"}
    return {}


def _food_data(user_input: dict[str, Any], unit: str) -> dict[str, Any]:
    return {
        CONF_NAME: user_input[CONF_NAME].strip(),
        CONF_ICON: user_input.get(CONF_ICON) or None,
        CONF_LEVELS: [
            {CONF_NAME: str(level[CONF_NAME]).strip(), CONF_TEMPERATURE: float(level[CONF_TEMPERATURE])}
            for level in user_input.get(CONF_LEVELS, [])
        ],
        CONF_UNIT: unit,
        CONF_SAFETY_FOOD: user_input.get(CONF_SAFETY_FOOD) or None,
    }


class FoodSubentryFlow(ConfigSubentryFlow):
    """A food no chart lists, with your own doneness levels. It is listed under the source Mine."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        unit = self.hass.config.units.temperature_unit
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _food_errors(user_input, _taken(self, SUBENTRY_FOOD, CONF_NAME))
            if not errors:
                data = _food_data(user_input, unit)
                return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_food_schema(), user_input or {}),
            description_placeholders={"unit": unit},
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        unit = subentry.data.get(CONF_UNIT) or self.hass.config.units.temperature_unit
        errors: dict[str, str] = {}
        if user_input is not None:
            taken = _taken(self, SUBENTRY_FOOD, CONF_NAME) - {subentry.data[CONF_NAME]}
            errors = _food_errors(user_input, taken)
            if not errors:
                data = _food_data(user_input, unit)
                return self.async_update_and_abort(self._get_entry(), subentry, title=data[CONF_NAME], data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(_food_schema(), user_input or dict(subentry.data)),
            description_placeholders={"unit": unit},
            errors=errors,
        )
