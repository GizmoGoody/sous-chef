"""Setting up Sous Chef, then adding probes, ambient sensors and foods to it."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sous_chef.const import DOMAIN

from .helpers import other_probe, rfx_gateway, rfx_meat


async def _sous_chef(hass: HomeAssistant) -> MockConfigEntry:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    return result["result"]


async def _add(hass: HomeAssistant, entry: MockConfigEntry, subentry_type: str, user_input: dict):
    result = await hass.config_entries.subentries.async_init((entry.entry_id, subentry_type), context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)


async def test_one_entry_and_its_options(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    assert entry.title == "Sous Chef"
    assert entry.options == {"keep_last": True}

    # Sous Chef holds everything in one entry
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"keep_last": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"keep_last": False}


async def test_known_probe_needs_only_the_device(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, channels = rfx_meat(hass, "RFX Probe Red")
    result = await _add(hass, entry, "probe", {"device": device, "colors": ["red", "black"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "RFX Probe Red"
    # Channel 0 is the internal temperature, channels 1 to 4 run from the tip, and the alarm threshold is left out
    assert subentry.data == {
        "device": device,
        "internal": channels[0],
        "channels": channels[1:],
        "colors": ["red", "black"],
        "auto_on": True,
    }

    # The same probe cannot be added twice
    result = await _add(hass, entry, "probe", {"device": device})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"device": "already_added"}


async def test_probe_with_one_sensor(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, (sensor,) = other_probe(hass, "Wired", 1)
    result = await _add(hass, entry, "probe", {"device": device})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data == {"device": device, "internal": sensor, "channels": [], "colors": [], "auto_on": False}


async def test_probe_with_several_sensors(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, sensors = other_probe(hass, "Multi", 3)
    result = await _add(hass, entry, "probe", {"device": device, "colors": ["blue"]})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sensors"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"internal": sensors[1], "channels": [sensors[2], sensors[1], sensors[0]], "auto_on": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    # The internal temperature is left out of the channels
    assert subentry.data == {
        "device": device,
        "internal": sensors[1],
        "channels": [sensors[2], sensors[0]],
        "colors": ["blue"],
        "auto_on": True,
    }


async def test_probe_with_the_lowest_of_its_channels(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, sensors = other_probe(hass, "Multi", 3)
    result = await _add(hass, entry, "probe", {"device": device})
    # The lowest of one channel is no internal temperature
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channels": [sensors[0]], "auto_on": False}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"internal": "no_internal"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channels": sensors, "auto_on": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data["internal"] is None
    assert subentry.data["channels"] == sensors


async def test_device_with_no_temperature(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, _ = other_probe(hass, "Empty", 0)
    result = await _add(hass, entry, "probe", {"device": device})
    assert result["errors"] == {"device": "no_temperature"}


async def test_ambient_sensors(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, sensors = other_probe(hass, "Gateway", 2)
    hass.states.async_set(sensors[0], "250", {"friendly_name": "Grill Ambient", "unit_of_measurement": "°F"})
    result = await _add(hass, entry, "ambient", {"device": device})
    assert result["step_id"] == "sensor"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"sensor": sensors[0]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "Grill Ambient"
    assert subentry.data == {"device": device, "sensor": sensors[0]}

    # The device's other sensor is the only one left, so it is added at once
    result = await _add(hass, entry, "ambient", {"device": device})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await _add(hass, entry, "ambient", {"device": device})
    assert result["errors"] == {"device": "already_added"}


async def test_alarm_thresholds_are_no_ambient_sensor(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    device, ambient = rfx_gateway(hass)
    # The gateway's alarm thresholds are temperature sensors too, but read no temperature
    result = await _add(hass, entry, "ambient", {"device": device})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data == {"device": device, "sensor": ambient}


async def test_food_of_your_own(hass: HomeAssistant) -> None:
    entry = await _sous_chef(hass)
    levels = [{"name": "Probe tender", "temperature": 203}, {"name": "Sliceable", "temperature": 195}]
    result = await _add(hass, entry, "food", {"name": " Brisket ", "icon": "mdi:cow", "levels": levels})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "Brisket"
    assert subentry.data == {
        "name": "Brisket",
        "icon": "mdi:cow",
        "levels": [{"name": "Probe tender", "temperature": 203.0}, {"name": "Sliceable", "temperature": 195.0}],
        "unit": hass.config.units.temperature_unit,
        "safety_food": None,
    }

    result = await _add(hass, entry, "food", {"name": "Pork butt", "safety_food": "pork_shoulder"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    butt = next(s for s in entry.subentries.values() if s.title == "Pork butt")
    assert butt.data["safety_food"] == "pork_shoulder"

    result = await _add(hass, entry, "food", {"name": "Brisket"})
    assert result["errors"] == {"name": "name_taken"}
    result = await _add(hass, entry, "food", {"name": "Ribs", "levels": [{"name": "Custom", "temperature": 1}]})
    assert result["errors"] == {"levels": "bad_levels"}
