"""A probe's source, food type and doneness.

Each carries the source's chart link as its url attribute, so the Sous Chef
Card can show where a target comes from. An ambient sensor's cook style sets
its target and alarm limits. Food type also carries the food's
government safe minimum and its chart; Doneness says whether the target is
below it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SousChefConfigEntry
from .entity import AmbientEntity, ProbeEntity
from .presets import COOK_STYLES, CUSTOM, MINE


async def async_setup_entry(
    hass: HomeAssistant, entry: SousChefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for subentry_id, probe in entry.runtime_data.probes.items():
        subentry = entry.subentries[subentry_id]
        async_add_entities(
            [
                SourceSelect(hass, subentry, probe, "source"),
                FoodTypeSelect(hass, subentry, probe, "food_type"),
                DonenessSelect(hass, subentry, probe, "doneness"),
            ],
            config_subentry_id=subentry_id,
        )
    for subentry_id, ambient in entry.runtime_data.ambients.items():
        async_add_entities(
            [CookStyleSelect(hass, entry.subentries[subentry_id], ambient, "cook_style")],
            config_subentry_id=subentry_id,
        )


class PresetSelect(ProbeEntity, SelectEntity):
    """A setting of the cook's preset."""

    _attr_entity_category = EntityCategory.CONFIG
    _unrecorded_attributes = frozenset({"url", "safety_chart", "safety_url"})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"url": self.probe.catalog.url(self.probe.source)}


class SourceSelect(PresetSelect):
    """The chef chart the presets come from, or the user's own foods."""

    @property
    def options(self) -> list[str]:
        return list(self.probe.catalog.sources)

    @property
    def current_option(self) -> str:
        return self.probe.source

    async def async_select_option(self, option: str) -> None:
        self.probe.set_source(option)


class FoodTypeSelect(PresetSelect):
    """What is cooking: one of the source's foods, or Other for any target."""

    @property
    def options(self) -> list[str]:
        return self.probe.foods

    @property
    def current_option(self) -> str:
        return self.probe.food

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        if minimum := self.probe.safe_minimum:
            attributes["safe_minimum"] = minimum.level.in_unit(self.probe.unit)
            if minimum.level.rest_minutes:
                attributes["safe_minimum_rest_minutes"] = minimum.level.rest_minutes
            if minimum.level.hold_minutes:
                attributes["safe_minimum_hold_minutes"] = minimum.level.hold_minutes
            attributes["safety_chart"] = minimum.chart.name
            attributes["safety_url"] = minimum.chart.url
        return attributes

    @property
    def icon(self) -> str | None:
        # A food of the user's own has its own icon; the built-in foods have theirs in icons.json
        if self.probe.source == MINE:
            return self.probe.catalog.icons.get(self.probe.food)
        return None

    async def async_select_option(self, option: str) -> None:
        self.probe.set_food(option)


class DonenessSelect(PresetSelect):
    """How done: one of the food's levels, or Custom for any other target."""

    @property
    def options(self) -> list[str]:
        return self.probe.doneness_options

    @property
    def current_option(self) -> str:
        return self.probe.doneness

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        level = self.probe.level
        attributes = super().extra_state_attributes
        if level and level.rest_minutes:
            attributes["rest_minutes"] = level.rest_minutes
        if level and level.hold_minutes:
            attributes["hold_minutes"] = level.hold_minutes
        # Flagged for the card to warn; the target itself is never changed
        if (below := self.probe.below_safe_minimum) is not None:
            attributes["below_safe_minimum"] = below
            attributes["safe_minimum"] = self.probe.safe_minimum.level.in_unit(self.probe.unit)  # type: ignore[union-attr]
        return attributes

    async def async_select_option(self, option: str) -> None:
        self.probe.set_doneness(option)


class CookStyleSelect(AmbientEntity, SelectEntity):
    """How the grill cooks: a preset sets its target and alarm limits, or Custom for any other.

    Its presets attribute gives each preset's target, low and high in the
    sensor's unit, so a card can show the numbers in its menu.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [*COOK_STYLES, CUSTOM]
    _unrecorded_attributes = frozenset({"presets"})

    @property
    def current_option(self) -> str:
        return self.ambient.cook_style

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"presets": {key: style.as_dict(self.ambient.unit) for key, style in COOK_STYLES.items()}}

    async def async_select_option(self, option: str) -> None:
        self.ambient.set_cook_style(option)
