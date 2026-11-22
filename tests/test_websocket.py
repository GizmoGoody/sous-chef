"""The preset charts, as the Sous Chef Card reads them."""

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.sous_chef.const import DOMAIN


async def test_charts(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    hass.config.country = "CA"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"keep_last": True},
        subentries_data=[
            ConfigSubentryData(
                data={"name": "Brisket", "icon": "mdi:cow", "levels": [{"name": "Probe tender", "temperature": 203}], "unit": "°F"},
                subentry_type="food",
                title="Brisket",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "sous_chef/charts"})
    response = await client.receive_json()
    assert response["success"]
    result = response["result"]
    # The government chart Sous Chef chose from the country
    assert result["safety"]["key"] == "health_canada"
    assert result["safety"]["url"].startswith("https://www.canada.ca/")
    sources = result["sources"]
    # Only chef charts, with the user's own foods last
    assert [s["key"] for s in sources] == ["thermoworks", "americas_test_kitchen", "mine"]
    thermoworks = sources[0]
    assert thermoworks["url"].startswith("https://www.thermoworks.com/")
    chicken = next(f for f in thermoworks["foods"] if f["key"] == "chicken")
    assert chicken["icon"] == "mdi:food-drumstick"
    assert chicken["levels"] == [{"key": "breast", "f": 165, "c": 74}, {"key": "dark_meat", "f": 175, "c": 79}]
    assert chicken["safe_minimum"] == {
        "f": 165,
        "c": 74,
        "chart": "Health Canada (Safe Cooking Temperatures)",
        "url": result["safety"]["url"],
    }
    tuna = next(f for f in thermoworks["foods"] if f["key"] == "tuna")
    assert tuna["safe_minimum"]["c"] == 70
    # No level is a safe minimum, and Other is no food of a chart
    assert all(level["key"] != "safe_minimum" for s in sources for f in s["foods"] for level in f["levels"])
    assert all(f["key"] != "other" for s in sources for f in s["foods"])
    (brisket,) = sources[-1]["foods"]
    assert brisket == {
        "key": "Brisket",
        "icon": "mdi:cow",
        "safe_minimum": None,
        "levels": [{"key": "Probe tender", "f": 203.0, "c": 95.0}],
    }
    assert sources[-1]["url"] is None


async def test_safe_minimum_falls_back(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    hass.config.country = "GB"
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"keep_last": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "sous_chef/charts"})
    result = (await client.receive_json())["result"]
    assert result["safety"]["key"] == "uk_fsa"
    foods = {f["key"]: f for f in result["sources"][0]["foods"]}
    assert foods["pork"]["safe_minimum"]["hold_minutes"] == 2
    # The UK chart does not cover beef: FoodSafety.gov's, with its rest
    assert foods["beef"]["safe_minimum"] == {
        "f": 145,
        "c": 63,
        "rest_minutes": 3,
        "chart": "FoodSafety.gov (Safe Minimum Internal Temperatures)",
        "url": "https://www.foodsafety.gov/food-safety-charts/safe-minimum-internal-temperatures",
    }


async def test_charts_before_setup(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "sous_chef/charts"})
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "not_found"
