"""Probes and ambient sensors: what they read, and the cook or alarm built on it.

A probe follows its internal temperature: one sensor, or the lowest of its
channels. A cook runs from the moment the probe is turned on (its Active
switch) until it is turned off. Its start is the lowest internal temperature
since it was turned on: once the probe is in the food, that is the food's own
temperature, so a warm reading in the air before it went in does not count.

A probe can turn itself on when it starts reporting (off its charger) and, if
it did, off again when it stops (back on its charger). A probe the user turned
on stays on until the user turns it off.

An ambient sensor reads the air in a grill, pit or oven. It has no cook, only
an alarm.

Every setting (the cook, the limits) is kept in Home Assistant's storage, so
every browser shows the same values and they last across restarts. A reading
that goes blank for a while (a lost signal, a restart) changes nothing. A
known probe's reading counts only while the probe is reporting (see
profiles.py), so a value left over from the last time it was used is no
reading.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_OFF,
    CONF_AUTO_ON,
    CONF_CHANNELS,
    CONF_COLORS,
    CONF_DEVICE,
    CONF_INTERNAL,
    CONF_SENSOR,
    DOMAIN,
    RATE_MAX_SPAN_S,
    RATE_MIN_CHANGE,
    RATE_MIN_SAMPLES,
    RATE_MIN_SPAN_S,
    STALL_RATE_F,
)
from .presets import CUSTOM, OTHER, Catalog, Level, SafeMinimum
from .profiles import CHARGER_TIMEOUT, freshness

SAMPLE_INTERVAL = timedelta(seconds=60)


class SettingsStore:
    """Every probe's and ambient sensor's settings in one entry, saved together."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, 1, f"{DOMAIN}.{entry_id}")
        self.data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self.data = await self._store.async_load() or {}

    @callback
    def save(self, subentry_id: str, settings: dict[str, Any]) -> None:
        self.data[subentry_id] = settings
        self._store.async_delay_save(lambda: self.data, 2)

    async def async_flush(self) -> None:
        """Save now: a reload reads the store again at once."""
        await self._store.async_save(self.data)

    @callback
    def forget(self, keep: set[str]) -> None:
        """Drop the settings of probes and ambient sensors that were removed."""
        for subentry_id in set(self.data) - keep:
            del self.data[subentry_id]
        self._store.async_delay_save(lambda: self.data, 2)


class Limits:
    """An alarm's high and low limits. Either may be empty: no limit.

    The low limit arms only once the temperature has reached it, so a cold
    start (a grill being lit, a probe going into cold food) raises no alarm.
    """

    def __init__(self, saved: dict[str, Any]) -> None:
        self.high: float | None = saved.get("alarm_high")
        self.low: float | None = saved.get("alarm_low")
        self.armed: bool = saved.get("alarm_armed", False)

    def arm(self, value: float | None) -> bool:
        """Arm the low limit once the value reaches it. True when that changed."""
        if value is not None and self.low is not None and not self.armed and value >= self.low:
            self.armed = True
            return True
        return False

    def alarm(self, value: float | None) -> bool:
        if value is None:
            return False
        return (self.high is not None and value > self.high) or (
            self.low is not None and self.armed and value < self.low
        )

    def as_dict(self) -> dict[str, Any]:
        return {"alarm_high": self.high, "alarm_low": self.low, "alarm_armed": self.armed}


class Followed:
    """Something that follows temperature sensors on one device, and tells its entities when anything changes."""

    def __init__(self, hass: HomeAssistant, store: SettingsStore, subentry_id: str, device_id: str) -> None:
        self.hass = hass
        self.id = subentry_id
        self.store = store
        self.device_id = device_id
        fresh = freshness(hass, device_id)
        self._seen_attribute = fresh.attribute if fresh else None
        self._stale_after = fresh.stale_after if fresh else None
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubscribes: list[CALLBACK_TYPE] = []

    @property
    def followed(self) -> list[str]:
        raise NotImplementedError

    @callback
    def async_start(self) -> None:
        self._unsubscribes.append(async_track_state_change_event(self.hass, self.followed, self._state_changed))

    @callback
    def async_stop(self) -> None:
        while self._unsubscribes:
            self._unsubscribes.pop()()

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _changed(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        raise NotImplementedError

    def value(self, entity_id: str) -> float | None:
        """A sensor's temperature, or None when it is not reporting."""
        state: State | None = self.hass.states.get(entity_id)
        if state is None or (value := _number(state.state)) is None:
            return None
        if self._seen_attribute and self._stale_after:
            seen = dt_util.parse_datetime(str(state.attributes.get(self._seen_attribute) or ""))
            if seen is None or dt_util.utcnow() - seen > self._stale_after:
                return None
        return value

    def unit_of(self, entity_id: str | None) -> str:
        state = self.hass.states.get(entity_id) if entity_id else None
        return (state.attributes.get("unit_of_measurement") if state else None) or UnitOfTemperature.FAHRENHEIT

    def _save(self) -> None:
        raise NotImplementedError


class Ambient(Followed):
    """An ambient sensor: the air in a grill, pit or oven, and its alarm."""

    def __init__(self, hass: HomeAssistant, store: SettingsStore, subentry_id: str, data: dict[str, Any]) -> None:
        super().__init__(hass, store, subentry_id, data[CONF_DEVICE])
        self.sensor: str = data[CONF_SENSOR]
        self.limits = Limits(store.data.get(subentry_id, {}))

    @property
    def followed(self) -> list[str]:
        return [self.sensor]

    @callback
    def async_start(self) -> None:
        super().async_start()
        if self.limits.arm(self.reading):
            self._save()

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        if self.limits.arm(self.reading):
            self._save()
        self._changed()

    @property
    def reading(self) -> float | None:
        return self.value(self.sensor)

    @property
    def unit(self) -> str:
        return self.unit_of(self.sensor)

    @property
    def alarm(self) -> bool:
        return self.limits.alarm(self.reading)

    @callback
    def set_limit(self, high: bool, value: float | None) -> None:
        if high:
            self.limits.high = value
        else:
            self.limits.low = value
            self.limits.armed = False
            self.limits.arm(self.reading)
        self._save()
        self._changed()

    def _save(self) -> None:
        self.store.save(self.id, self.limits.as_dict())


class Probe(Followed):
    """One probe's cook, worked out from its internal temperature."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: SettingsStore,
        subentry_id: str,
        data: dict[str, Any],
        catalog: Catalog,
        keep_last: bool,
    ) -> None:
        super().__init__(hass, store, subentry_id, data[CONF_DEVICE])
        # None: the lowest of the channels
        self.internal: str | None = data.get(CONF_INTERNAL)
        self.channels: list[str] = list(data.get(CONF_CHANNELS) or [])
        self.colors: list[str] = list(data.get(CONF_COLORS) or [])
        self.auto_on: bool = bool(data.get(CONF_AUTO_ON))
        self.auto_off: bool = bool(data.get(CONF_AUTO_OFF))
        self.catalog = catalog
        self.keep_last = keep_last
        saved = store.data.get(subentry_id, {})
        self.active: bool = saved.get("active", False)
        # The probe turned itself on, so it may turn itself off; a probe the user turned on stays on
        self.auto_started: bool = saved.get("auto_started", False)
        self.source: str = saved.get("source", catalog.default_source)
        if self.source not in catalog.sources:
            self.source = catalog.default_source
        self.food: str = saved.get("food", OTHER)
        if self.food not in catalog.foods(self.source):
            self.food = OTHER
        self.doneness: str = saved.get("doneness", CUSTOM)
        if self.doneness not in self.doneness_options:
            self.doneness = CUSTOM
        self.target: float | None = saved.get("target")
        self.start: float | None = saved.get("start")
        self.pull_early: float = saved.get("pull_early", 0)
        self.limits = Limits(saved)
        self._samples: deque[tuple[float, float]] = deque()
        self._last_reading: float | None = None
        # When the probe last had a reading, for telling that it is back on its charger
        self._last_reported = dt_util.utcnow()

    @property
    def followed(self) -> list[str]:
        return list(dict.fromkeys([*([self.internal] if self.internal else []), *self.channels]))

    # -- Following the reading --------------------------------------------

    @callback
    def async_start(self) -> None:
        super().async_start()
        self._unsubscribes.append(async_track_time_interval(self.hass, self._tick, SAMPLE_INTERVAL))
        self._last_reading = self.reading
        self._last_reported = dt_util.utcnow()
        self._update()

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        reading = self.reading
        # A probe that only reports once it is off its charger turns itself on.
        # A first state (no old state) is a sensor being set up, not a probe
        # taken off its charger, so it is left alone.
        turned_on = (
            self.auto_on
            and not self.active
            and event.data["old_state"] is not None
            and self._last_reading is None
            and reading is not None
        )
        self._last_reading = reading
        if reading is not None:
            self._last_reported = dt_util.utcnow()
        if turned_on:
            self.set_active(True, automatic=True)
            return
        self._update()
        self._changed()

    @callback
    def _tick(self, _now: datetime) -> None:
        # A reading that does not change sends no state change; sampling it
        # anyway lets the rate fall to zero, which shows a stall
        self._sample()
        now = dt_util.utcnow()
        if self.reading is not None:
            self._last_reported = now
        elif self.auto_off and self.auto_started and self.active and now - self._last_reported >= CHARGER_TIMEOUT:
            # It turned itself on off its charger, and has stopped reporting: it is back on its charger
            self.set_active(False)
            return
        self._changed()

    def _update(self) -> None:
        self._sample()
        reading = self.reading
        if not self.active or reading is None:
            return
        changed = self.limits.arm(reading)
        # The cook's start is the lowest reading since the probe was turned on
        if self.start is None or reading < self.start:
            self.start = reading
            changed = True
        if changed:
            self._save()

    def _sample(self) -> None:
        value = self.reading
        now = dt_util.utcnow().timestamp()
        if value is None:
            return
        self._samples.append((now, value))
        while self._samples and self._samples[0][0] < now - RATE_MAX_SPAN_S:
            self._samples.popleft()

    # -- What the entities show -------------------------------------------

    @property
    def reading(self) -> float | None:
        """The internal temperature: its sensor, or the lowest of the channels."""
        if self.internal:
            return self.value(self.internal)
        values = [v for v in map(self.value, self.channels) if v is not None]
        return min(values) if values else None

    @property
    def max(self) -> float | None:
        """The highest of the channels right now."""
        values = [v for v in map(self.value, self.channels) if v is not None]
        return max(values) if values else None

    @property
    def unit(self) -> str:
        return self.unit_of(self.internal or next(iter(self.channels), None))

    @property
    def cooking(self) -> bool:
        """On, with a reading and a target: progress, done and stalled mean something."""
        return self.active and self.reading is not None and self.target is not None

    @property
    def rate(self) -> float | None:
        """Degrees per minute: the slope of the readings over a window that fits how fast they move.

        The window starts at the newest reading and reaches back until it holds
        enough readings over enough time, and the temperature has moved enough
        that one step of the sensor does not swing the slope. A fast rise keeps
        it short; a slow one lets it grow to its longest.
        """
        if not self.active or len(self._samples) < RATE_MIN_SAMPLES:
            return None
        newest_t, newest_v = self._samples[-1]
        window: list[tuple[float, float]] = []
        for t, v in reversed(self._samples):
            window.append((t, v))
            if (
                len(window) >= RATE_MIN_SAMPLES
                and newest_t - t >= RATE_MIN_SPAN_S
                and abs(newest_v - v) >= RATE_MIN_CHANGE
            ):
                break
        if len(window) < RATE_MIN_SAMPLES or newest_t - window[-1][0] < RATE_MIN_SPAN_S:
            return None
        n = len(window)
        mean_t = sum(t for t, _ in window) / n
        mean_v = sum(v for _, v in window) / n
        spread = sum((t - mean_t) ** 2 for t, _ in window)
        if spread == 0:
            return None
        slope = sum((t - mean_t) * (v - mean_v) for t, v in window) / spread
        return slope * 60

    @property
    def stall_rate(self) -> float:
        return STALL_RATE_F if self.unit == UnitOfTemperature.FAHRENHEIT else STALL_RATE_F * 5 / 9

    @property
    def done_temperature(self) -> float | None:
        """The target, less Pull early by."""
        return None if self.target is None else self.target - (self.pull_early or 0)

    @property
    def done(self) -> bool:
        return self.cooking and self.reading >= self.done_temperature  # type: ignore[operator]

    @property
    def stalled(self) -> bool:
        rate = self.rate
        return self.cooking and not self.done and rate is not None and rate < self.stall_rate

    @property
    def done_at(self) -> datetime | None:
        rate, reading = self.rate, self.reading
        if not self.cooking or rate is None or rate < self.stall_rate or self.done:
            return None
        return dt_util.utcnow() + timedelta(minutes=(self.done_temperature - reading) / rate)  # type: ignore[operator]

    @property
    def progress(self) -> float | None:
        reading, start, target = self.reading, self.start, self.target
        if not self.active or reading is None or start is None or target is None or target <= start:
            return None
        return max(0.0, min(100.0, (reading - start) / (target - start) * 100))

    @property
    def alarm(self) -> bool:
        return self.active and self.limits.alarm(self.reading)

    @property
    def foods(self) -> list[str]:
        return self.catalog.foods(self.source)

    @property
    def doneness_options(self) -> list[str]:
        return [*self.catalog.levels(self.source, self.food), CUSTOM]

    @property
    def level(self) -> Level | None:
        """The chosen doneness level, or None for Custom."""
        return self.catalog.levels(self.source, self.food).get(self.doneness)

    @property
    def safe_minimum(self) -> SafeMinimum | None:
        """The government safe minimum for the food, or None for a food with none."""
        return self.catalog.safe_minimum(self.source, self.food)

    @property
    def below_safe_minimum(self) -> bool | None:
        """Whether the target, of a named doneness or Custom, is below the food's safe minimum. None without both."""
        minimum = self.safe_minimum
        if minimum is None or self.target is None:
            return None
        return self.target < minimum.level.in_unit(self.unit)

    # -- Changing the cook ------------------------------------------------

    @callback
    def set_active(self, active: bool, automatic: bool = False) -> None:
        """Turning a probe on starts a new cook; turning it off ends it."""
        if active == self.active:
            return
        self.active = active
        self.auto_started = active and automatic
        if active:
            self.start = None
            self.limits.armed = False
            self._samples.clear()
            if not self.keep_last:
                self.source, self.food, self.doneness, self.target = self.catalog.default_source, OTHER, CUSTOM, None
            self._update()
        self._save()
        self._changed()

    def _choose(self, food: str, doneness: str | None) -> None:
        """A food and a doneness: None or a doneness the food lacks is its first; Custom stays Custom."""
        levels = self.catalog.levels(self.source, food)
        if doneness != CUSTOM and doneness not in levels:
            doneness = next(iter(levels), CUSTOM)
        self.food, self.doneness = food, doneness
        if doneness in levels:
            self.target = levels[doneness].in_unit(self.unit)

    @callback
    def set_source(self, source: str) -> None:
        """A new source keeps the food when it has it."""
        self.source = source
        if self.food in self.foods:
            self._choose(self.food, self.doneness)
        else:
            self.food, self.doneness = OTHER, CUSTOM
        self._save()
        self._changed()

    @callback
    def set_food(self, food: str) -> None:
        self._choose(food, None)
        self._save()
        self._changed()

    @callback
    def set_doneness(self, doneness: str) -> None:
        self._choose(self.food, doneness)
        self._save()
        self._changed()

    @callback
    def set_target(self, target: float) -> None:
        self.target = target
        # A target of the food's own levels keeps its doneness name
        self.doneness = next(
            (d for d, level in self.catalog.levels(self.source, self.food).items() if level.in_unit(self.unit) == target),
            CUSTOM,
        )
        self._save()
        self._changed()

    @callback
    def set_pull_early(self, value: float) -> None:
        self.pull_early = value
        self._save()
        self._changed()

    @callback
    def set_limit(self, high: bool, value: float | None) -> None:
        if high:
            self.limits.high = value
        else:
            self.limits.low = value
            self.limits.armed = False
            if self.active:
                self.limits.arm(self.reading)
        self._save()
        self._changed()

    def _save(self) -> None:
        self.store.save(self.id, {
            "active": self.active,
            "auto_started": self.auto_started,
            "source": self.source,
            "food": self.food,
            "doneness": self.doneness,
            "target": self.target,
            "start": self.start,
            "pull_early": self.pull_early,
            **self.limits.as_dict(),
        })


def _number(state: str) -> float | None:
    if state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        return float(state)
    except ValueError:
        return None
