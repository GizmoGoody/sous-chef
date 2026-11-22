"""Constants for Sous Chef."""

from homeassistant.const import Platform

DOMAIN = "sous_chef"

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

# The entry's options
CONF_KEEP_LAST = "keep_last"

# The kinds of subentry
SUBENTRY_PROBE = "probe"
SUBENTRY_AMBIENT = "ambient"
SUBENTRY_FOOD = "food"

# A probe's and an ambient sensor's data
CONF_DEVICE = "device"
CONF_INTERNAL = "internal"
CONF_CHANNELS = "channels"
CONF_COLORS = "colors"
CONF_AUTO_ON = "auto_on"
CONF_SENSOR = "sensor"

# A food's data
CONF_NAME = "name"
CONF_ICON = "icon"
CONF_LEVELS = "levels"
CONF_TEMPERATURE = "temperature"
CONF_UNIT = "unit"
CONF_SAFETY_FOOD = "safety_food"

# Home Assistant's named colors, for a probe's colored bands
COLORS = [
    "red",
    "pink",
    "purple",
    "deep-purple",
    "indigo",
    "blue",
    "light-blue",
    "cyan",
    "teal",
    "green",
    "light-green",
    "lime",
    "yellow",
    "amber",
    "orange",
    "deep-orange",
    "brown",
    "grey",
    "black",
    "white",
]

# The rate: the window holds at least this many values over at least the
# shortest span, and grows until the temperature has moved enough to measure
# or the window reaches the longest span
RATE_MIN_SAMPLES = 3
RATE_MIN_SPAN_S = 120
RATE_MAX_SPAN_S = 900
RATE_MIN_CHANGE = 2.0

# Rising less than this many °F a minute short of the target is a stall
STALL_RATE_F = 0.05
