# Sous Chef

*For the grill, the smoker and the kitchen.*

Sous Chef turns any food thermometer in Home Assistant into a cook. You say what you are cooking and how done you want it, from a chef's chart you trust, and it tells you when that is below your government's safe minimum. It tells you how far along the food is, how fast it is heating, when it will be done, whether it has stalled, and when anything is out of range.

Every cook is kept as entities, so every browser shows the same cook at once, a change made in one shows in all, and automations can use it. It needs no helpers and no automations.

The [Sous Chef Card](https://github.com/GizmoGoody/sous-chef-card) shows it on a dashboard.

> [!WARNING]
> **Alpha developmental software. Use with caution.** Do not rely on it alone for food safety. Check the temperature with a second thermometer before serving.

## Install

1. Go to **Settings → Marketplace**, then ⋮ → **Add from link**. Enter `GizmoGoody/sous-chef`, type **Integration**.
2. Install **Sous Chef**. For a pre-release, use ⋮ → **Install another version**.

## Set up

1. **Settings → Devices & services → Add integration → Sous Chef.** There is one Sous Chef entry. It holds all your probes and ambient sensors.
2. On its page, choose **Add probe**, then choose the probe device and, optionally, its colors (several, in order, for a striped probe). A probe is added once and used anywhere.
   - A **ThermoWorks RFX MEAT** needs nothing else: its internal temperature is channel 0, and its channels 1 to 4 run from the tip.
   - A device with **one** temperature sensor needs nothing else.
   - A device with **several** temperature sensors asks for its internal temperature (one sensor, or empty for the lowest of the channels) and its channels in order from the tip.
3. Choose **Add ambient sensor** for each sensor that reads the air in a grill, pit or oven. It gets a target, a cook style and alarms, and no food.
4. Choose **Add food** for a food no chef chart lists, with your own doneness levels. It is listed under the source **Mine**. Optionally, choose **Safe minimum as**: the built-in food whose government safe minimum applies to it.
5. **Configure** sets whether a new cook keeps the last source, food type, doneness and target (on by default).

## How a cook runs

- A cook runs while the probe's **Active** switch is on. Turn it on whenever you like, even with the probe still on its charger, and set up the cook.
- A probe turns itself on when it comes off its charger, and off when it goes back. Both options are on by default; turn either off in the probe's **Reconfigure** (**Turn on when taken off the charger**, **Turn off when put back on the charger**).
- A probe on its charger sends nothing, so going back on the charger means it has stopped reporting: about 6 minutes for an RFX probe, 5 minutes for others.
- You can turn a probe on by hand while it is on its charger, to set up the cook. Once it comes off the charger, it turns off when it goes back. A probe you turned on by hand while it was already reporting stays on until you turn it off, so a lost signal never ends that cook.
- Each change Sous Chef makes by itself is logged at info level and fires the event `sous_chef_probe_auto_on` or `sous_chef_probe_auto_off`, with the probe's `device_id` and the `reason`.
- The **internal temperature** is the one temperature that stands for the inside of the food. Progress, Rate, Done at, Done, Stalled and the probe's alarm all use it.
- The cook's start is the lowest internal temperature since the probe was turned on. Once the probe is in the food, that is the food's own temperature. Progress runs from that start to the target.
- A restart changes nothing. Turning the probe off ends the cook.
- An RFX probe counts as reporting only while it sends new data. ThermoWorks Cloud keeps showing a probe's last value while it is on its charger, and that old value is treated as no reading.

## Entities

On each probe's own device, beside its temperature sensors. Settings are Configuration entities: they are on the device page and stay out of automatic dashboards.

| Entity | Kind | What it is |
| --- | --- | --- |
| Active | Control | On while the probe is cooking. Turning it on starts a new cook. |
| Source | Configuration | The chef chart the presets come from, or Mine. |
| Food type | Configuration | What is cooking (one food per probe): the source's foods, or Other for any target. |
| Doneness | Configuration | The food's named levels, or Custom for any other target. Choosing one sets the target. |
| Target | Configuration | The temperature to reach. |
| Pull early by | Configuration | Done turns on this many degrees before the target, for carryover while the food rests. |
| Alarm high, Alarm low | Configuration | The internal temperature must stay below and above these while the probe is on. 0 is no limit. |
| Progress | Sensor | How far the internal temperature has come from the cook's start to the target. |
| Rate | Sensor | Degrees per minute, over a window that adjusts itself: about 2 minutes when the temperature moves fast, up to 15 when it moves slowly. |
| Done at | Sensor | When the internal temperature will reach the target, less Pull early by, at its current rate. |
| Done | Sensor | On once the internal temperature reaches the target, less Pull early by. |
| Stalled | Sensor | On while it rises less than 0.05 °F a minute short of the target. |
| Alarm | Sensor | On while the internal temperature is above Alarm high or below Alarm low. |
| Max | Sensor | The highest of the probe's channels. Only for probes with channels. |

On each ambient sensor's device:

| Entity | Kind | What it is |
| --- | --- | --- |
| Target | Configuration | The grill's target temperature, 100 to 700 °F (40 to 370 °C). 0 is no target. Its history is recorded, so a dashboard can graph it beside the ambient reading. |
| Cook style | Configuration | A preset that sets Target, Alarm low and Alarm high, or Custom. Setting any of those three by hand makes it Custom; choosing Custom changes nothing else. |
| Alarm high, Alarm low | Configuration | The ambient temperature must stay below and above these. 0 is no limit. |
| Alarm | Sensor | On while the temperature is out of range. |

| Cook style | Target | Alarm low and high |
| --- | --- | --- |
| Smoke | 225 °F (107 °C) | ±15 °F (±8 °C) |
| Low and slow | 250 °F (121 °C) | ±25 °F (±14 °C) |
| Roast | 325 °F (163 °C) | ±25 °F (±14 °C) |
| Hot and fast | 375 °F (191 °C) | ±25 °F (±14 °C) |
| Bake | 400 °F (204 °C) | ±25 °F (±14 °C) |
| Sear | 550 °F (288 °C) | ±50 °F (±28 °C) |

An Alarm low turns on only once the temperature has first reached it, so lighting a grill or putting a probe in cold food raises no alarm.

### Presets

Every preset names its source: one published chef chart. Each value is copied from its chart in the units it gives. Where a chart gives a range, the preset is the low end of the range. A doneness is always a named level from its chart (Rare, Medium rare, Breast, Dark meat and so on). A food a chart covers only with a safe minimum is not offered for it.

| Source | Chart |
| --- | --- |
| ThermoWorks (Chef-Recommended Temperatures) | [thermoworks.com](https://www.thermoworks.com/blogs/thermoblog/chef-recommended-tw-approved) |
| America's Test Kitchen (How to Know When Food Is Done) | [americastestkitchen.com](https://www.americastestkitchen.com/cooksillustrated/articles/1390-how-to-know-when-food-is-done) |
| Mine | Your own foods, added with **Add food**. |

### Safe minimums

Sous Chef picks the government chart from your Home Assistant country. A food that chart does not cover takes FoodSafety.gov's safe minimum. Sous Chef never changes a target: when the target is below the food's safe minimum, the Doneness entity says so, and the Sous Chef Card warns.

| Chart | Country |
| --- | --- |
| [FoodSafety.gov (Safe Minimum Internal Temperatures)](https://www.foodsafety.gov/food-safety-charts/safe-minimum-internal-temperatures) | US, and any country without its own chart |
| [Health Canada (Safe Cooking Temperatures)](https://www.canada.ca/en/health-canada/services/general-food-safety-tips/safe-internal-cooking-temperatures.html) | CA |
| [UK Food Standards Agency (Cooking Your Food)](https://www.gov.uk/government/publications/cooking-your-food/cooking-your-food) | GB |
| [FSANZ (Food Safety Basics)](https://www.foodstandards.gov.au/consumer/prevention-of-foodborne-illness/food-safety-basics) | AU, NZ |

### For the Sous Chef Card

- The **Done at** sensor's `projection` attribute: the readings Sous Chef expects from now to the target, as `time` (ISO 8601) and `temperature` points. Sous Chef's rate model is a constant rate, so the points are now, Done at and, with Pull early by set, the target. It is empty while Done at has no value.
- The **Progress** sensor's attributes: `internal` (entity ID, or empty for the lowest of the channels), `channels` (entity IDs, from the tip), `colors` (Home Assistant color names, in order) and `start`.
- **Source**, **Food type** and **Doneness** carry the chef chart's link as `url`. Doneness also carries `rest_minutes` or `hold_minutes` when the chart gives one.
- **Food type** carries the food's government safe minimum: `safe_minimum` (in the probe's unit), `safe_minimum_rest_minutes` or `safe_minimum_hold_minutes` when the chart gives one, and `safety_chart` and `safety_url`, the chart's name and link.
- **Doneness** carries `below_safe_minimum` (true or false) and `safe_minimum` whenever the food has a safe minimum and there is a target, Custom included.
- The ambient **Alarm** sensor's `sensor` attribute is the ambient sensor's entity ID.
- The ambient **Cook style** select's `presets` attribute maps each preset (not Custom) to its `target`, `low` and `high` in the sensor's unit.
- The websocket command `sous_chef/charts` gives `safety` (the government chart Sous Chef chose: `key`, `name`, `url`) and `sources`, every source's whole chart in the Source select's order: each source's `key`, `url` and `foods`. Each food has its `key`, `icon`, `safe_minimum` (`f`, `c`, `rest_minutes` or `hold_minutes` when the chart gives one, `chart` and `url`; null for a food with none) and `levels` (`key`, `f`, `c`, and `rest_minutes` or `hold_minutes` when the chart gives one).

## License

MIT. See [LICENSE](LICENSE).
