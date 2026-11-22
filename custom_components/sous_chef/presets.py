"""Where presets come from: chef charts, government safety charts, and foods the user adds.

A source is one published chef chart. It gives named doneness levels (Rare,
Medium rare, Breast, Dark meat and so on), each a temperature, for the foods
it covers. A food a chart covers only with a safe minimum is left out of it.

A safety chart is one government chart of safe minimum temperatures. Sous
Chef picks it from Home Assistant's country; it is not a source. A food the
country's chart does not cover takes FoodSafety.gov's safe minimum. A
doneness below its food's safe minimum is allowed and flagged, never changed.

One probe cooks one food, so every food is one kind of meat or fish. Foods
share one list of names and icons across every chart, so switching source
keeps the food when the new source has it. Each value is copied from its
chart in the units the chart gives. A chart that gives only one unit has the
other converted and rounded to a whole degree, as the other charts round it.

A chart that gives a range is given here by the low end of the range: the
temperature at which the food reaches that doneness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import CONF_ICON, CONF_LEVELS, CONF_NAME, CONF_SAFETY_FOOD, CONF_TEMPERATURE, CONF_UNIT

CUSTOM = "custom"
OTHER = "other"
MINE = "mine"
DEFAULT_ICON = "mdi:food"


@dataclass(frozen=True)
class Level:
    """A temperature in °F and in °C, with any rest or hold time its chart gives."""

    f: float
    c: float
    # The chart says to rest the food this long after cooking
    rest_minutes: int | None = None
    # The chart says to hold the core at this temperature this long
    hold_minutes: int | None = None

    def in_unit(self, unit: str) -> float:
        if unit == UnitOfTemperature.FAHRENHEIT:
            return self.f
        if unit == UnitOfTemperature.CELSIUS:
            return self.c
        return round(TemperatureConverter.convert(self.c, UnitOfTemperature.CELSIUS, unit), 1)

    @classmethod
    def of(cls, temperature: float, unit: str) -> Level:
        """A level given in one unit."""
        f = TemperatureConverter.convert(temperature, unit, UnitOfTemperature.FAHRENHEIT)
        c = TemperatureConverter.convert(temperature, unit, UnitOfTemperature.CELSIUS)
        return cls(f=round(f, 1), c=round(c, 1))

    def as_dict(self) -> dict[str, Any]:
        return {
            "f": self.f,
            "c": self.c,
            **({"rest_minutes": self.rest_minutes} if self.rest_minutes else {}),
            **({"hold_minutes": self.hold_minutes} if self.hold_minutes else {}),
        }


@dataclass(frozen=True)
class Source:
    """One chef chart, or the user's own foods: named doneness levels for each food."""

    key: str
    url: str | None
    foods: dict[str, dict[str, Level]]


@dataclass(frozen=True)
class SafetyChart:
    """One government chart: the safe minimum for each food it covers."""

    key: str
    name: str
    url: str
    countries: tuple[str, ...]
    foods: dict[str, Level]


@dataclass(frozen=True)
class SafeMinimum:
    """A food's safe minimum, and the chart it comes from."""

    chart: SafetyChart
    level: Level


# Every food, in the order the Food type select lists them. The last ones
# have a safe minimum but no named doneness in any chef chart: they are
# offered only for a food of the user's own to take its safe minimum from.
FOODS = [
    "beef",
    "veal",
    "lamb",
    "pork",
    "fresh_ham",
    "precooked_ham",
    "brisket",
    "pork_shoulder",
    "pork_ribs",
    "chicken",
    "turkey",
    "tuna",
    "swordfish",
    "marlin",
    "salmon",
    "white_fish",
    "ground_beef",
    "ground_pork",
    "ground_lamb",
    "ground_poultry",
    "shellfish",
    "egg_dishes",
    "leftovers",
]

RED_MEAT = ("beef", "veal", "lamb")
PORK = ("pork", "fresh_ham", "pork_shoulder", "pork_ribs")
POULTRY = ("chicken", "turkey")
FISH = ("tuna", "swordfish", "marlin", "salmon", "white_fish")
GROUND_MEAT = ("ground_beef", "ground_pork", "ground_lamb")


def _each(foods: tuple[str, ...], level: Level) -> dict[str, Level]:
    return dict.fromkeys(foods, level)


FOODSAFETY_GOV = SafetyChart(
    key="foodsafety_gov",
    name="FoodSafety.gov (Safe Minimum Internal Temperatures)",
    url="https://www.foodsafety.gov/food-safety-charts/safe-minimum-internal-temperatures",
    countries=("US",),
    foods={
        # Steaks, roasts and chops, which take in brisket, pork shoulder and ribs
        **_each((*RED_MEAT, "brisket", *PORK), Level(145, 63, rest_minutes=3)),
        **_each(GROUND_MEAT, Level(160, 71)),
        **_each((*POULTRY, "ground_poultry"), Level(165, 74)),
        **_each(FISH, Level(145, 63)),
    },
)

SAFETY_CHARTS = [
    FOODSAFETY_GOV,
    SafetyChart(
        key="health_canada",
        name="Health Canada (Safe Cooking Temperatures)",
        url="https://www.canada.ca/en/health-canada/services/general-food-safety-tips/safe-internal-cooking-temperatures.html",
        countries=("CA",),
        foods={
            # Pieces and whole cuts: medium rare is the lowest the chart gives
            **_each((*RED_MEAT, "brisket"), Level(145, 63)),
            # Pork, including ham, loin and ribs
            **_each((*PORK, "precooked_ham"), Level(160, 71)),
            **_each(GROUND_MEAT, Level(160, 71)),
            # Pieces. A whole bird is 82 °C, but a probe reads one piece of it.
            **_each((*POULTRY, "ground_poultry"), Level(165, 74)),
            **_each(FISH, Level(158, 70)),
            "shellfish": Level(165, 74),
            "egg_dishes": Level(165, 74),
            "leftovers": Level(165, 74),
        },
    ),
    SafetyChart(
        key="uk_fsa",
        name="UK Food Standards Agency (Cooking Your Food)",
        url="https://www.gov.uk/government/publications/cooking-your-food/cooking-your-food",
        countries=("GB",),
        foods=_each(
            (*GROUND_MEAT, *PORK, "precooked_ham", *POULTRY, "ground_poultry"), Level(158, 70, hold_minutes=2)
        ),
    ),
    SafetyChart(
        key="fsanz",
        name="FSANZ (Food Safety Basics)",
        url="https://www.foodstandards.gov.au/consumer/prevention-of-foodborne-illness/food-safety-basics",
        countries=("AU", "NZ"),
        foods=_each((*GROUND_MEAT, *POULTRY, "ground_poultry"), Level(167, 75)),
    ),
]

SOURCES = [
    Source(
        key="thermoworks",
        url="https://www.thermoworks.com/blogs/thermoblog/chef-recommended-tw-approved",
        foods={
            **dict.fromkeys(
                RED_MEAT,
                {
                    "rare": Level(120, 49),
                    "medium_rare": Level(130, 54),
                    "medium": Level(135, 57),
                    "medium_well": Level(145, 63),
                    "well_done": Level(155, 68),
                },
            ),
            "pork": {"usda_done": Level(145, 63), "well_done": Level(150, 66)},
            "fresh_ham": {"done": Level(160, 71)},
            "precooked_ham": {"done": Level(140, 60)},
            **dict.fromkeys(("brisket", "pork_shoulder", "pork_ribs"), {"done": Level(190, 88)}),
            **dict.fromkeys(POULTRY, {"breast": Level(165, 74), "dark_meat": Level(175, 79)}),
            **dict.fromkeys(("tuna", "swordfish", "marlin"), {"done": Level(125, 52)}),
            **dict.fromkeys(("salmon", "white_fish"), {"done": Level(140, 60)}),
        },
    ),
    Source(
        key="americas_test_kitchen",
        url="https://www.americastestkitchen.com/cooksillustrated/articles/1390-how-to-know-when-food-is-done",
        foods={
            "chicken": {"white_meat": Level(160, 71), "dark_meat": Level(175, 79)},
            "tuna": {"rare": Level(110, 43), "medium_rare": Level(125, 52)},
            "salmon": {"medium_rare": Level(125, 52)},
            "white_fish": {"medium": Level(140, 60)},
        },
    ),
]


@dataclass
class Catalog:
    """The sources in the order the Source select lists them, with the user's foods last, and the safety chart.

    The safety chart is the one for Home Assistant's country, or
    FoodSafety.gov when the country has none.
    """

    sources: dict[str, Source]
    safety: SafetyChart = FOODSAFETY_GOV
    icons: dict[str, str] = field(default_factory=dict)
    # The food a food of the user's own takes its safe minimum from
    safety_foods: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, country: str | None, foods: list[dict[str, Any]]) -> Catalog:
        mine = Source(
            key=MINE,
            url=None,
            foods={
                food[CONF_NAME]: {
                    level[CONF_NAME]: Level.of(level[CONF_TEMPERATURE], food[CONF_UNIT])
                    for level in food.get(CONF_LEVELS, [])
                }
                for food in foods
            },
        )
        return cls(
            sources={s.key: s for s in [*SOURCES, mine]},
            safety=next((c for c in SAFETY_CHARTS if country in c.countries), FOODSAFETY_GOV),
            icons={food[CONF_NAME]: food.get(CONF_ICON) or DEFAULT_ICON for food in foods},
            safety_foods={food[CONF_NAME]: food[CONF_SAFETY_FOOD] for food in foods if food.get(CONF_SAFETY_FOOD)},
        )

    @property
    def default_source(self) -> str:
        return next(iter(self.sources))

    def foods(self, source: str) -> list[str]:
        """A source's foods, then Other for any target."""
        foods = self.sources[source].foods
        return [*(f for f in FOODS if f in foods), *(f for f in foods if f not in FOODS), OTHER]

    def levels(self, source: str, food: str) -> dict[str, Level]:
        return self.sources[source].foods.get(food, {})

    def url(self, source: str) -> str | None:
        return self.sources[source].url

    def safe_minimum(self, source: str, food: str) -> SafeMinimum | None:
        """The food's safe minimum: the country's chart, else FoodSafety.gov. None for Other."""
        key = self.safety_foods.get(food) if source == MINE else food
        for chart in (self.safety, FOODSAFETY_GOV):
            if key in chart.foods:
                return SafeMinimum(chart, chart.foods[key])
        return None
