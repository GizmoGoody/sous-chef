"""The preset charts, for the Sous Chef Card's chart view.

Entities carry only the chosen source's foods and levels. This command gives
every source's whole chart, in the order the Source select lists them, so a
card can show a chart and set a probe from it. Each food carries its
government safe minimum, so a card can mark the levels below it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.icon import async_get_icons

from .const import DOMAIN
from .presets import MINE, OTHER, Catalog, SafeMinimum


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_charts)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/charts"})
@websocket_api.async_response
async def ws_charts(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Every source's chart, and the government safety chart Sous Chef chose."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Sous Chef is not set up")
        return
    icons = await async_get_icons(hass, "entity", [DOMAIN])
    food_icons = icons.get(DOMAIN, {}).get("select", {}).get("food_type", {}).get("state", {})
    connection.send_result(msg["id"], charts(entries[0].runtime_data.catalog, food_icons))


def charts(catalog: Catalog, food_icons: dict[str, str]) -> dict[str, Any]:
    """The catalog as plain data. Foods of the user's own take their own icons.

    Each food carries its safe minimum: from the country's safety chart, or
    FoodSafety.gov when that chart does not cover it, with that chart's name
    and link. A food with none has null.
    """
    return {
        "safety": {"key": catalog.safety.key, "name": catalog.safety.name, "url": catalog.safety.url},
        "sources": [
            {
                "key": source.key,
                "url": source.url,
                "foods": [
                    {
                        "key": food,
                        "icon": catalog.icons.get(food) if source.key == MINE else food_icons.get(food),
                        "safe_minimum": _safe_minimum(catalog.safe_minimum(source.key, food)),
                        "levels": [
                            {"key": key, **level.as_dict()} for key, level in catalog.levels(source.key, food).items()
                        ],
                    }
                    for food in catalog.foods(source.key)
                    if food != OTHER
                ],
            }
            for source in catalog.sources.values()
        ],
    }


def _safe_minimum(minimum: SafeMinimum | None) -> dict[str, Any] | None:
    if minimum is None:
        return None
    return {**minimum.level.as_dict(), "chart": minimum.chart.name, "url": minimum.chart.url}
