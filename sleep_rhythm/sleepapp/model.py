"""Educational sleep-timing model (pure Python, no third-party packages).

Concepts from sleep research (circadian necessary sleep; alertness = circadian
sleep threshold - sleep pressure). The equations and every number below are
simplified design choices for this app, not a published model or its
parameters. See docs/MODEL.md.

Time spans are integrated in UTC; circadian phase uses the user's local clock.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from statistics import mean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = "rhythm-educational-2.2"
UTC = timezone.utc
STEP = timedelta(minutes=15)      # candidate grid and chart step (the plan's 15-minute unit)
FINE = timedelta(minutes=5)       # target-period check and necessary-sleep search
WINDOW = timedelta(minutes=30)    # width of the recommended bedtime window
TAU_WAKE, TAU_SLEEP = 18.2, 4.2   # hours; classic two-process time constants
CALIBRATION_MARGIN_HOURS = 0.25   # reference sleeper's necessary sleep ends 15 min before waking
SHIFT_LIMIT = timedelta(minutes=60)  # largest model-driven advance proposed for one night
NECESSARY_HORIZON_HOURS = 16
ONSET_NOTE = 0.05                 # AL at bedtime above this: the model says "not sleepy yet"

# key: (label, minimum h, published maximum h or None, model recommendation, search maximum h)
AGE_GROUPS = {
    "newborn": ("만 0–3개월", 14, 17, False, 17),
    "infant": ("만 4–11개월", 12, 16, False, 16),
    "toddler": ("만 1–2세", 11, 14, False, 14),
    "preschool": ("만 3–5세", 10, 13, False, 13),
    "school": ("만 6–12세", 9, 12, True, 12),
    "teen": ("만 13–17세", 8, 10, True, 10),
    "adult": ("만 18–60세", 7, None, True, 9),
    "older": ("만 61–64세", 7, 9, True, 9),
    "senior": ("만 65세 이상", 7, 8, True, 8),
}


class InputError(ValueError):
    """Safe user-facing validation failure."""


# ---------------------------------------------------------------- validation

def obj(value, name):
    if not isinstance(value, dict):
        raise InputError(f"{name}: 객체 형식이 필요합니다.")
    return value


def number(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{name}: 올바른 숫자를 입력하세요.")
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise InputError(f"{name}: 올바른 숫자를 입력하세요.") from None
    if not math.isfinite(value):
        raise InputError(f"{name}: 올바른 숫자를 입력하세요.")
    if not lo <= value <= hi:
        raise InputError(f"{name}: {lo}~{hi} 범위로 입력하세요.")
    return value


def text(value, name, maximum=100):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise InputError(f"{name}: 1~{maximum}자의 문자열이 필요합니다.")
    return value


def get_zone(name):
    text(name, "시간대", 80)
    # Korea has had no daylight saving time since 1988, so a fixed +09:00 offset
    # keeps Seoul working on Windows without the optional tzdata package.
    if name == "Asia/Seoul":
        return timezone(timedelta(hours=9), "Asia/Seoul")
    if name == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):  # OSError: e.g. a directory name such as "America"
        raise InputError("시간대를 찾을 수 없습니다. IANA 시간대 이름(예: Asia/Seoul)을 확인하거나 tzdata를 설치하세요.") from None


def parse_time(value, zone, label="시각"):
    text(value, label, 40)
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::00)?(?:Z|[+-]\d\d:\d\d)?", value):
        raise InputError(f"{label}: 날짜와 시각을 분 단위 ISO 형식으로 입력하세요.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InputError(f"{label}: 존재하지 않는 날짜 또는 시각입니다.") from None
    if not 2000 <= dt.year <= 2100:
        raise InputError(f"{label}: 2000~2100년만 지원합니다.")
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    valid = []
    for fold in (0, 1):
        stamp = dt.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if stamp.astimezone(zone).replace(tzinfo=None) == dt and stamp not in valid:
            valid.append(stamp)
    if not valid:
        raise InputError(f"{label}: 서머타임 전환으로 존재하지 않는 시각입니다.")
    if len(valid) > 1:
        raise InputError(f"{label}: 서머타임 전환으로 두 번 존재하는 시각입니다. ISO 입력에 UTC 오프셋(예: -04:00)을 붙이세요.")
    return valid[0]


def iso(t, zone=UTC):
    return t.astimezone(zone).isoformat(timespec="minutes")


def hour(t, zone):
    local = t.astimezone(zone)
    return local.hour + local.minute / 60 + local.second / 3600


def hours_between(a, b):
    return (b - a).total_seconds() / 3600


def distance(a, b):
    """Shortest distance between two clock hours, 0~12."""
    return abs((a - b + 12) % 24 - 12)


def circular(values):
    """Circular mean of clock hours and its concentration R (0~1)."""
    if not values:
        return None, 0.0
    x = math.fsum(math.cos(v * math.tau / 24) for v in values) / len(values)
    y = math.fsum(math.sin(v * math.tau / 24) for v in values) / len(values)
    return (math.atan2(y, x) * 24 / math.tau) % 24, math.hypot(x, y)


@dataclass(frozen=True)
class Episode:
    id: str
    start: datetime
    end: datetime
    kind: str
    sleepiness_wake: int | None = None
    light_minutes: float | None = None

    @property
    def hours(self):
        return hours_between(self.start, self.end)


def profile_data(raw):
    raw = obj(raw, "설정")
    key = raw.get("age_group", "teen")
    if not isinstance(key, str) or key not in AGE_GROUPS:
        raise InputError("연령대를 선택하세요.")
    label, lo, hi, eligible, search_maximum = AGE_GROUPS[key]
    zone_name = raw.get("timezone", "Asia/Seoul")
    zone = get_zone(zone_name)
    schedule = raw.get("schedule", "day")
    if schedule not in ("day", "shift"):
        raise InputError("생활 유형을 선택하세요.")
    # v1.0 backups contained "desired_hours"; it is accepted and ignored.
    return {"age_group": key, "label": label, "minimum": lo, "maximum": hi,
            "search_maximum": search_maximum, "eligible": eligible and schedule == "day",
            "schedule": schedule, "timezone": zone_name}, zone


def parse_records(raw, zone, now=None):
    if not isinstance(raw, list) or len(raw) > 1500:
        raise InputError("수면 기록은 최대 1,500개까지 입력할 수 있습니다.")
    records, ids = [], set()
    for i, row in enumerate(raw):
        obj(row, f"수면 기록 {i + 1}")
        rid = text(row.get("id"), "기록 ID", 80)
        if rid in ids:
            raise InputError("중복된 수면 기록 ID가 있습니다.")
        ids.add(rid)
        start = parse_time(row.get("start"), zone, "잠든 시각")
        end = parse_time(row.get("end"), zone, "기상 시각")
        if not 1 <= (end - start).total_seconds() / 60 <= 1200:
            raise InputError("수면 종료는 시작 이후여야 하며, 한 기록은 1분~20시간이어야 합니다.")
        if now and end > now + timedelta(minutes=2):
            raise InputError("실제 수면 기록에 미래의 기상 시각을 입력할 수 없습니다.")
        kind = row.get("kind", "main")
        if kind not in ("main", "nap"):
            raise InputError("수면 종류는 main 또는 nap이어야 합니다.")
        sleepy = row.get("sleepiness_wake")
        if sleepy is not None:
            sleepy = number(sleepy, "기상 직후 졸림", 1, 9)
            if sleepy != int(sleepy):
                raise InputError("졸림 정도는 1~9의 정수입니다.")
            sleepy = int(sleepy)
        light = row.get("light_minutes")
        if light is not None:
            light = number(light, "취침 전 2시간 밝은 빛 노출", 0, 120)
        records.append(Episode(rid, start, end, kind, sleepy, light))
    records.sort(key=lambda r: r.start)
    for a, b in zip(records, records[1:]):
        if b.start < a.end:
            raise InputError("서로 겹치는 수면 기록이 있습니다. 주수면과 낮잠 시간도 겹칠 수 없습니다.")
    if records and (records[-1].end - records[0].start).days > 730:
        raise InputError("한 파일에는 최대 2년 범위의 기록을 보관하세요.")
    return records


def parse_observations(raw, zone, now=None):
    if not isinstance(raw, list) or len(raw) > 400:
        raise InputError("활동 중 졸림 기록은 최대 400개까지 입력할 수 있습니다.")
    result, ids = [], set()
    for row in raw:
        obj(row, "졸림 기록")
        rid = text(row.get("id"), "졸림 기록 ID", 80)
        if rid in ids:
            raise InputError("중복된 졸림 기록 ID가 있습니다.")
        ids.add(rid)
        at = parse_time(row.get("at"), zone, "졸림 측정 시각")
        value = number(row.get("sleepiness"), "활동 중 졸림", 1, 9)
        if value != int(value):
            raise InputError("졸림 정도는 1~9의 정수입니다.")
        if now and at > now + timedelta(minutes=2):
            raise InputError("졸림 측정 시각은 미래일 수 없습니다.")
        result.append({"id": rid, "at": at, "sleepiness": int(value)})
    return sorted(result, key=lambda r: r["at"])


def validate_dataset(payload, now=None):
    obj(payload, "입력")
    version = payload.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise InputError("지원하지 않는 파일 버전입니다.")
    profile, zone = profile_data(payload.get("profile", {}))
    records = parse_records(payload.get("records", []), zone, now)
    observations = parse_observations(payload.get("observations", []), zone, now)
    return profile, zone, records, observations


def circadian_trough(mid, wake):
    """Clock hour of the threshold minimum: halfway between habitual mid-sleep and
    habitual wake time (for 8-hour sleep: 2 h after mid-sleep = 2 h before waking).
    App design rule built from the plan's 'mid-sleep and wake time', not a measured phase."""
    if mid is None or wake is None:
        return None
    return circular([mid, wake])[0]


def recent_history(records, at, zone, with_episodes=True):
    """Use one main episode per wake date, strictly before ``at``.

    A missing or duplicated main-sleep day ends the continuous block (missing
    nights are never imputed). The block holds at most 14 nights.
    """
    relevant = [r for r in records if at - timedelta(days=22) <= r.end <= at]
    by_day = {}
    for r in relevant:
        if r.kind == "main":
            by_day.setdefault(r.end.astimezone(zone).date(), []).append(r)
    chosen, duplicate = [], False
    if by_day:
        day = max(by_day)
        for _ in range(14):
            items = by_day.get(day, [])
            if len(items) != 1:
                duplicate = len(items) > 1
                break
            chosen.append(items[0])
            day -= timedelta(days=1)
    chosen.reverse()
    usable = [r for r in relevant if chosen and r.start >= chosen[0].start] if with_episodes else None
    mid, concentration = circular([hour(r.start + (r.end - r.start) / 2, zone) for r in chosen])
    bed, _ = circular([hour(r.start, zone) for r in chosen])
    wake, _ = circular([hour(r.end, zone) for r in chosen])
    return {"mains": chosen, "episodes": usable, "days": len(chosen),
            "midpoint": mid, "bed": bed, "wake": wake, "trough": circadian_trough(mid, wake),
            "concentration": concentration, "duplicate_day": duplicate,
            "stale": not chosen or (at - chosen[-1].end) > timedelta(hours=36)}


# ---------------------------------------------------------------- physiology

@lru_cache(maxsize=64)
def _calibration(reference_hours, tau_wake, tau_sleep):
    """Threshold level/amplitude for one reference sleep duration D.

    For a person who sleeps D hours every night at the same clock time (steady
    state), S rises to C exactly at sleep onset, and S falls back below C
    CALIBRATION_MARGIN_HOURS before the wake time (end of necessary sleep). The
    threshold minimum lies halfway between mid-sleep and waking (D/4 after
    mid-sleep), so only D matters. App calibration rule, not a fit to data.
    """
    d = float(reference_hours)
    rise = math.exp(-(24 - d) / tau_wake)
    fall = math.exp(-d / tau_sleep)
    s_onset = (1 - rise) / (1 - rise * fall)
    s_end = s_onset * math.exp(-(d - CALIBRATION_MARGIN_HOURS) / tau_sleep)
    trough = d / 4
    c_on = math.cos(math.tau * (-d / 2 - trough) / 24)
    c_end = math.cos(math.tau * (d / 2 - CALIBRATION_MARGIN_HOURS - trough) / 24)
    amplitude = (s_onset - s_end) / (c_end - c_on)
    return {"level": s_onset + amplitude * c_on, "amplitude": amplitude,
            "onset_pressure": s_onset, "offset_pressure": s_onset * fall}


@dataclass(frozen=True)
class Model:
    """One set of model assumptions. ``reference_hours`` = age-group minimum."""
    reference_hours: float = 8.0
    phase: float = 0.0
    tau_wake: float = TAU_WAKE
    tau_sleep: float = TAU_SLEEP
    name: str = "기본 가정"

    @property
    def calibration(self):
        return _calibration(self.reference_hours, self.tau_wake, self.tau_sleep)

    def variants(self):
        """The sensitivity set: this model plus four changed assumptions."""
        tw, ts = self.tau_wake, self.tau_sleep
        return (self,
                Model(self.reference_hours, self.phase - 1, tw, ts, "일주기 위상 1시간 이르게"),
                Model(self.reference_hours, self.phase + 1, tw, ts, "일주기 위상 1시간 늦게"),
                Model(self.reference_hours, self.phase, tw * .8, ts * .8, "시간상수 20% 짧게"),
                Model(self.reference_hours, self.phase, tw * 1.2, ts * 1.2, "시간상수 20% 길게"))


DEFAULT_MODEL = Model()


def advance(s, hours, asleep, tau_wake=TAU_WAKE, tau_sleep=TAU_SLEEP):
    """Exact exponential update of sleep pressure S (0~1).

    Awake: S moves a fixed fraction of the way towards 1 per unit time;
    asleep: S loses a fixed fraction per unit time (the plan's 'add or subtract a
    fixed ratio every 15 minutes', computed exactly for any duration)."""
    if hours < 0:
        raise ValueError("Time must not run backwards")
    if asleep:
        return s * math.exp(-hours / tau_sleep)
    return 1 - (1 - s) * math.exp(-hours / tau_wake)


def threshold(at, trough, zone, model=DEFAULT_MODEL):
    """Circadian sleep threshold C(t) = level - A*cos(2*pi*(t - trough)/24), lowest at
    ``trough`` (clock hour) shifted by the model's phase assumption."""
    cal = model.calibration
    return cal["level"] - cal["amplitude"] * math.cos(math.tau * (hour(at, zone) - trough - model.phase) / 24)


def pressure(at, episodes, model=DEFAULT_MODEL, initial=None):
    """S(at) from recorded sleep; unrecorded time counts as wake."""
    return pressure_series([at], episodes, model, initial)[0]


def pressure_series(times, episodes, model=DEFAULT_MODEL, initial=None):
    """S at each of the ascending ``times`` in one pass over the episodes.

    The first episode starts from the balanced sleep-onset pressure. Its effect
    fades within days, which is why the first 4 days are a warm-up period."""
    if initial is None:
        initial = model.calibration["onset_pressure"]
    if not episodes:
        return [initial for _ in times]
    tw, ts = model.tau_wake, model.tau_sleep
    s, cursor, i, out = initial, episodes[0].start, 0, []
    for t in times:
        if t < cursor:
            raise ValueError("Cannot infer before history begins or go backwards")
        while i < len(episodes) and episodes[i].start < t:
            ep = episodes[i]
            if ep.start > cursor:
                s = advance(s, hours_between(cursor, ep.start), False, tw, ts)
                cursor = ep.start
            end = min(ep.end, t)
            if end > cursor:
                s = advance(s, hours_between(cursor, end), True, tw, ts)
                cursor = end
            if ep.end > t:
                break  # t falls inside this episode
            i += 1
        if t > cursor:
            s = advance(s, hours_between(cursor, t), False, tw, ts)
            cursor = t
        out.append(s)
    return out


def scan_target(start, end, sample):
    """AL over the target period on 5-minute steps: mean by the midpoint rule (last
    step weighted by its real length), minimum over every step's ends and
    midpoint, and the share of time with AL < 0."""
    weighted = below = total = 0.0
    minimum = sample(start)
    t = start
    while t < end:
        nxt = min(t + FINE, end)
        width = (nxt - t).total_seconds()
        value = sample(t + (nxt - t) / 2)
        weighted += value * width
        below += width if value < 0 else 0
        total += width
        minimum = min(minimum, value, sample(nxt))
        t = nxt
    return {"mean": weighted / total, "minimum": minimum, "below_fraction": below / total, "seconds": total}


def scan_blocks(blocks, sample):
    """scan_target over several separate periods (e.g. 1st and 5th class),
    combined with each period weighted by its length."""
    parts = [scan_target(a, b, sample) for a, b in blocks]
    total = sum(p["seconds"] for p in parts)
    return {"mean": sum(p["mean"] * p["seconds"] for p in parts) / total,
            "minimum": min(p["minimum"] for p in parts),
            "below_fraction": sum(p["below_fraction"] * p["seconds"] for p in parts) / total,
            "seconds": total}


def necessary_sleep_end(bed, s_bed, c_at, tau_sleep=TAU_SLEEP):
    """End of the model's 'necessary sleep' for continuous sleep from ``bed``.

    ``c_at(t)`` gives C(t). Returns the start of the final run in which S <= C
    lasts to the 16-hour horizon (5-minute resolution, starting at ``bed``):
    waking at or after it is not forced wakefulness in the model. ``None`` if S
    is still above C at the horizon."""
    ratio = math.exp(-(FINE.total_seconds() / 3600) / tau_sleep)
    s, run_start = s_bed, None
    for i in range(NECESSARY_HORIZON_HOURS * 12 + 1):
        t = bed + i * FINE
        if s <= c_at(t):
            run_start = run_start or t
        else:
            run_start = None
        s *= ratio
    return run_start


class Scenario:
    """One model variant applied to one plan. Recorded sleep all ends by ``now``
    and candidate bedtimes are never before ``now``, so S(bed) follows from S(now)
    exactly; C(t) values are cached."""

    def __init__(self, model, hist, profile, zone, now, wake, blocks):
        self.model, self.profile, self.zone = model, profile, zone
        self.now, self.wake, self.blocks = now, wake, list(blocks)
        self.trough = hist["trough"]
        self.s_now = pressure(now, hist["episodes"], model)
        self._c, self._e = {}, {}

    def c(self, at):
        value = self._c.get(at)
        if value is None:
            value = self._c[at] = threshold(at, self.trough, self.zone, self.model)
        return value

    def decay(self, at):
        """exp(-(at - wake)/tau_wake): awake after the wake time, S(at) = 1 - (1 - S_wake) * decay."""
        value = self._e.get(at)
        if value is None:
            value = self._e[at] = math.exp(-hours_between(self.wake, at) / self.model.tau_wake)
        return value

    def s_at(self, t):
        return advance(self.s_now, hours_between(self.now, t), False, self.model.tau_wake, self.model.tau_sleep)

    def evaluate(self, bed):
        """Simulate sleeping from ``bed`` until the wake time and score the target period."""
        tw, ts = self.model.tau_wake, self.model.tau_sleep
        s_bed = self.s_at(bed)
        duration = hours_between(bed, self.wake)
        s_wake = advance(s_bed, duration, True, tw, ts)
        gap = 1 - s_wake

        def alert(at):  # AL = C - S with S = 1 - (1 - S_wake) * exp(-(at - wake)/tau_wake)
            return self.c(at) - 1 + gap * self.decay(at)

        target = scan_blocks(self.blocks, alert)
        end = necessary_sleep_end(bed, s_bed, self.c, ts)
        p = self.profile
        return {"bed": bed, "wake": self.wake, "hours": duration,
                "mean_alertness": target["mean"], "minimum_alertness": target["minimum"],
                "below_fraction": target["below_fraction"],
                "onset_alertness": self.c(bed) - s_bed,
                "wake_pressure": s_wake, "wake_alertness": self.c(self.wake) - s_wake,
                "necessary_end": end,
                "necessary_ok": end is not None and end <= self.wake,
                "target_ok": target["minimum"] >= 0,
                "meets_minimum": duration >= p["minimum"] - 1e-9,
                "within_maximum": duration <= p["search_maximum"] + 1e-9}


def candidate_public(c, zone):
    out = {}
    for key, value in c.items():
        if isinstance(value, datetime):
            out[key] = iso(value, zone)
        elif isinstance(value, float):
            out[key] = round(value, 5)
        else:
            out[key] = value
    out["alertness_label"] = "high" if c["target_ok"] else "low"
    return out


def grid_times(earliest, latest, zone):
    """Local quarter-hours from ``earliest`` to ``latest``; steps in UTC so DST
    transitions keep exact elapsed time."""
    cur = earliest.replace(second=0, microsecond=0)
    if cur < earliest:
        cur += timedelta(minutes=1)
    while cur.astimezone(zone).minute % 15:
        cur += timedelta(minutes=1)
    result = []
    while cur <= latest:
        result.append(cur)
        cur += STEP
    return result


def candidate_times(earliest, latest, zone, extra=()):
    """Quarter-hour grid plus the exact range ends and the given boundary times
    (age-minimum limit, search-maximum limit, the user's plan) inside the range,
    so limits are never rounded to the grid."""
    times = set(grid_times(earliest, latest, zone))
    times.update((earliest, latest))
    times.update(t for t in extra if t is not None and earliest <= t <= latest)
    return sorted(times)


# ------------------------------------------------------------ recommendation

def _hard_ok(r):
    return r["meets_minimum"] and r["within_maximum"]


def _complete(r):
    return _hard_ok(r) and r["target_ok"]


def _latest(rows, predicate=lambda r: True):
    chosen = [r for r in rows if predicate(r)]
    return max(chosen, key=lambda r: r["bed"]) if chosen else None


def decide(rows, anchor=None, anchor_in_range=False):
    """Decision rule over evaluated candidates.

    1. Hard constraints (never relaxed): age minimum <= duration <= search
       maximum, inside the user's bedtime range. Every deadline reported is
       computed only over candidates that meet them.
    2. Model condition: AL >= 0 for the whole target activity (no forced
       wakefulness while it matters). The necessary-sleep check (S <= C by the
       wake time) is reported for every candidate and for the current plan, but
       does not decide on its own: its end time typically moves only 15-30 minutes
       per hour of bedtime change, so as a rule it would demand very large shifts.
    3. With a fixed wake time an earlier bedtime always raises model alertness, so
       instead of always picking the earliest time the rule changes the current
       plan (``anchor``) as little as possible: keep it if acceptable, otherwise
       move to the nearest acceptable time and show the 30 minutes there. The
       anchor is the user's own plan or habit, so a plan longer than the search
       maximum is never shortened (only the minimum and the model condition apply).
    4. One night's change is capped at ``cap`` = anchor - max(advance the hard
       constraints require, SHIFT_LIMIT). If the model condition needs a bedtime
       earlier than the cap, the plan stops at the cap ('partial', reason
       'large_shift') and the model's own deadline is reported separately.
    """
    feasible = [r for r in rows if _hard_ok(r)]
    complete = [r for r in feasible if r["target_ok"]]
    deadlines = {
        "minimum": _latest(feasible),
        "target": _latest(complete),
        "overall": _latest(complete),
        "necessary": _latest(feasible, lambda r: r["necessary_ok"]),
    }
    result = {"status": "infeasible", "mode": None, "deadlines": deadlines, "window": [],
              "best": None, "deadline": None, "max_alertness": None, "partial_reason": None}
    if not feasible:
        return result
    if complete:
        pool, status, reason = complete, "ready", None

        def acceptable(r):
            return r["meets_minimum"] and r["target_ok"]
    else:
        pool, status, reason = feasible, "partial", "unattainable"

        def acceptable(r):
            return r["meets_minimum"]
    keep = anchor is not None and anchor_in_range and acceptable(anchor)
    if complete and anchor is not None and not keep:
        hard_shift = max(timedelta(0), anchor["bed"] - deadlines["minimum"]["bed"])
        cap = anchor["bed"] - max(hard_shift, SHIFT_LIMIT)
        if deadlines["overall"]["bed"] < cap:
            pool = [r for r in feasible if r["bed"] <= cap] or [min(feasible, key=lambda r: r["bed"])]
            status, reason = "partial", "large_shift"
    first = min(pool, key=lambda r: r["bed"])
    last = max(pool, key=lambda r: r["bed"])
    if keep:
        mode, window = "keep", [anchor]
    elif anchor is None or anchor["bed"] <= first["bed"]:
        mode = "earliest" if anchor is None else "delay"
        window = [r for r in pool if first["bed"] <= r["bed"] <= first["bed"] + WINDOW]
    elif anchor["bed"] >= last["bed"]:
        mode = "advance"
        window = [r for r in pool if last["bed"] - WINDOW <= r["bed"] <= last["bed"]]
    else:  # inside the acceptable span but not acceptable itself (not expected with monotone conditions)
        mode = "nearest"
        window = [min(pool, key=lambda r: abs(r["bed"] - anchor["bed"]))]
    window.sort(key=lambda r: r["bed"])
    max_alert = max(feasible, key=lambda r: (round(r["mean_alertness"], 9), -r["bed"].timestamp()))
    result.update(status=status, mode=mode, window=window, best=window[0], deadline=last,
                  max_alertness=max_alert, partial_reason=reason)
    return result


def habitual_bed_before(wake, hist, zone):
    """The habitual (average) bedtime on the local clock, on the night before ``wake``.

    Rounded to 5 minutes because it is an average, not a measured instant. Built
    from the local date and clock time, so a daylight-saving change that night
    shortens or lengthens the sleep exactly as it would in real life."""
    if hist["bed"] is None:
        return None
    minutes = round(hist["bed"] * 12) * 5 % 1440
    wake_day = wake.astimezone(zone).date()
    for back in (0, 1):
        local = datetime.combine(wake_day - timedelta(days=back), time(minutes // 60, minutes % 60), tzinfo=zone)
        bed = local.astimezone(UTC)
        if timedelta(hours=1) <= wake - bed <= timedelta(hours=20):
            return bed
    return None


def duration_text(minutes):
    hours, rest = divmod(int(minutes), 60)
    return f"{hours}시간 {rest}분" if hours and rest else f"{hours}시간" if hours else f"{rest}분"


def parse_targets(plan, zone):
    """Target activity as one or more periods: ``targets`` = [[start, end], ...]
    (e.g. selected class periods) or the older ``target_start``/``target_end``.
    Overlapping or touching periods are merged."""
    raw = plan.get("targets")
    if raw is None:
        raw = [[plan.get("target_start"), plan.get("target_end")]]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise InputError("집중할 시간은 1~12개 구간으로 입력하세요.")
    blocks = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise InputError("집중할 시간 구간 형식이 올바르지 않습니다.")
        a = parse_time(item[0], zone, "활동 시작")
        b = parse_time(item[1], zone, "활동 종료")
        if not a < b:
            raise InputError("활동 종료는 시작보다 늦어야 합니다.")
        blocks.append((a, b))
    blocks.sort()
    merged = [blocks[0]]
    for a, b in blocks[1:]:
        if a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def recommend(payload, now=None):
    now = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    profile, zone, records, _ = validate_dataset(payload, now)
    plan = obj(payload.get("plan"), "목표 일정")
    wake = parse_time(plan.get("wake"), zone, "필수 기상")
    blocks = parse_targets(plan, zone)
    target_start, target_end = blocks[0][0], blocks[-1][1]
    auto_range = not plan.get("earliest") and not plan.get("latest")
    if auto_range:
        # Phone mode: search from now (or the age-group search maximum) until one
        # hour short of the age minimum, so the effect of a later bedtime is visible.
        earliest = max(now, wake - timedelta(hours=profile["search_maximum"]))
        latest = max(earliest, wake - timedelta(hours=profile["minimum"] - 1))
        if not earliest < wake:
            raise InputError("꼭 일어나야 하는 시각이 이미 지났어요. 다음 기상 시각을 입력해 주세요.")
    else:
        earliest = parse_time(plan.get("earliest"), zone, "가장 이른 취침")
        latest = parse_time(plan.get("latest"), zone, "가장 늦은 취침")
    if not earliest <= latest < wake <= target_start:
        raise InputError("이른 취침 ≤ 늦은 취침 < 기상 ≤ 활동 시작 순서여야 해요. 집중할 시간이 기상 시각보다 늦어야 해요.")
    if not auto_range and latest < now:
        raise InputError("잠들 수 있는 범위가 모두 지났습니다. 범위를 현재 이후로 바꾸세요.")
    if wake > now + timedelta(hours=48) or target_end > wake + timedelta(hours=24):
        raise InputError("기상은 앞으로 48시간 이내, 활동 종료는 기상 후 24시간 이내로 입력하세요.")
    if wake - earliest > timedelta(hours=20) or sum((b - a for a, b in blocks), timedelta()) > timedelta(hours=12):
        raise InputError("가장 이른 취침은 기상 전 20시간 이내, 집중할 시간은 모두 합쳐 12시간 이내여야 합니다.")
    warnings = []
    if earliest < now:
        earliest = now
        if not auto_range:
            warnings.append("가장 이른 취침 시각이 이미 지나서 지금 이후의 후보만 비교했어요.")
    if latest < earliest:
        latest = earliest
    baseline, baseline_source = None, None
    if plan.get("baseline"):
        baseline = parse_time(plan["baseline"], zone, "현재 계획 취침")
        if not baseline < wake or wake - baseline > timedelta(hours=20):
            raise InputError("지금 계획한 잠드는 시각은 기상 전 20시간 이내여야 합니다.")
        baseline_source = "input"
        if baseline < now:
            warnings.append("입력한 계획 취침 시각이 이미 지나서 비교에서 제외했어요.")
            baseline, baseline_source = None, None

    hist = recent_history(records, now, zone)
    response = {"model_version": VERSION, "profile": profile, "history_days": hist["days"],
                "status": "ready", "warnings": warnings, "candidates": [], "chart": [],
                "target_start": iso(target_start, zone), "target_end": iso(target_end, zone),
                "targets": [[iso(a, zone), iso(b, zone)] for a, b in blocks], "auto_range": auto_range,
                "wake": iso(wake, zone),
                "search": {"earliest": iso(earliest, zone), "latest": iso(latest, zone)}}
    duplicate_note = ("같은 기상 날짜에 밤잠(주수면)이 2개 이상 있어요. 그날의 대표 밤잠 하나만 두고 나머지는 "
                      "낮잠으로 바꿔 주세요. 그날보다 앞선 기록은 계산에 쓰지 않았어요.")
    if not profile["eligible"]:
        response.update(status="tracking_only", message="이 연령·생활 유형에는 기록과 수면량 안내만 제공해요. 영유아(낮잠 포함 수면)와 교대근무에는 이 단순한 밤잠 모형을 쓰지 않아요.")
        return response
    if hist["days"] < 5 or hist["stale"]:
        response.update(status="warmup", message="최근 연속 5일 이상의 밤잠 기록이 필요해요. 처음 4일은 모형 준비 기간이에요. 마지막 밤잠에서 깬 지 36시간이 지났다면 최근 기록을 먼저 추가해 주세요.")
        if hist["duplicate_day"]:
            response["warnings"].append(duplicate_note)
        return response
    if hist["concentration"] < .5:
        response.update(status="irregular", message="수면 중간 시각이 날마다 많이 달라서 하나의 24시간 리듬으로 설명하기 어려워요. 기록은 그대로 두고 이번 추천은 쉬어요.")
        return response
    if not 4 <= hist["wake"] <= 13 or not (hist["bed"] >= 17 or hist["bed"] <= 5):
        response.update(status="tracking_only", message="최근 기록은 낮에 자는 패턴에 가까워요. 추천은 밤에 자고 오전에 일어나는 밤잠에만 제공하고, 기록은 계속할 수 있어요.")
        return response
    if not 4 <= hour(wake, zone) <= 13:
        response.update(status="tracking_only", message="추천은 오전(04:00~13:00)에 일어나는 밤잠만 계획해요. 다른 시간에 일어난다면 기록 기능을 써 주세요.")
        return response

    if hist["duplicate_day"]:
        warnings.append(duplicate_note)
    if hist["days"] < 10:
        warnings.append("예비 추천이에요. 10~14일을 기록하면 더 긴 수면 이력이 반영돼요. 정확도가 검증된다는 뜻은 아니에요.")
    if target_start - wake < timedelta(minutes=60):
        warnings.append("일어난 지 1시간 안에 집중할 시간이 있어요. 이 모형은 잠에서 깬 직후의 멍한 상태(수면 관성)를 계산하지 않아요.")
    warnings.append("기록된 낮잠은 수면압에 반영해요. 지금부터 잠들 때까지 낮잠이 없고, 누운 뒤 바로 잠들며 밤중에 깨지 않는다고 가정해요.")

    model = Model(reference_hours=profile["minimum"])
    if baseline is None:
        habitual = habitual_bed_before(wake, hist, zone)
        if habitual is not None and habitual >= now:
            baseline, baseline_source = habitual, "habitual"
    if auto_range and baseline is not None and now <= baseline < earliest:
        # The automatic range starts at the search maximum; a longer habit stays in
        # the comparison because the app never tells anyone to sleep less than they do.
        earliest = baseline
        response["search"]["earliest"] = iso(earliest, zone)
    anchor_in_range = baseline is not None and earliest <= baseline <= latest
    cutoff = wake - timedelta(hours=profile["minimum"])
    long_cutoff = wake - timedelta(hours=profile["search_maximum"])
    beds = candidate_times(earliest, latest, zone, (cutoff, long_cutoff, baseline if anchor_in_range else None))
    scenario = Scenario(model, hist, profile, zone, now, wake, blocks)
    rows = [scenario.evaluate(b) for b in beds]
    anchor = scenario.evaluate(baseline) if baseline else None
    choice = decide(rows, anchor, anchor_in_range)
    deadlines = choice["deadlines"]
    response["deadlines"] = {k: iso(v["bed"], zone) if v else None for k, v in deadlines.items()}
    response["candidates"] = [candidate_public(r, zone) for r in rows]
    response["phase"] = {"sleep_midpoint_hour": round(hist["midpoint"], 3),
                         "habitual_wake_hour": round(hist["wake"], 3),
                         "threshold_minimum_hour": round(hist["trough"], 3),
                         "habitual_bed_hour": round(hist["bed"], 3),
                         "concentration": round(hist["concentration"], 3),
                         "reference_hours": model.reference_hours}
    if anchor:
        published = profile["maximum"]
        response["baseline"] = {**candidate_public(anchor, zone), "source": baseline_source,
                                "exceeds_recommended": published is not None and anchor["hours"] > published + 1e-9}
    else:
        response["baseline"] = None

    if choice["status"] == "infeasible":
        if any(r["meets_minimum"] for r in rows):
            reason = "too_long"
            message = f"입력한 범위에서는 모두 이 연령대의 탐색 상한({profile['search_maximum']}시간)보다 오래 자게 돼요."
        elif cutoff < now:
            reason = "minimum_unreachable"
            message = f"지금 잠들어도 이 기상 시각까지 최소 {profile['minimum']}시간을 채울 수 없어요. 기상 시각을 늦출 수 있는지 확인해 보세요."
        else:
            reason = "too_late"
            message = f"입력한 범위에는 연령별 최소 수면시간({profile['minimum']}시간)을 채우는 취침 시각이 없어요."
        response.update(status="infeasible", infeasible_reason=reason, message=message,
                        latest_for_minimum=iso(cutoff, zone), earliest_within_maximum=iso(long_cutoff, zone),
                        minimum_hours=profile["minimum"], minimum_reachable=cutoff >= now)
        return response

    best, deadline = choice["best"], choice["deadline"]
    response.update(status=choice["status"], mode=choice["mode"],
                    best=candidate_public(best, zone), deadline=candidate_public(deadline, zone),
                    window={"start": iso(choice["window"][0]["bed"], zone),
                            "end": iso(choice["window"][-1]["bed"], zone)})
    max_alert = choice["max_alertness"]
    response["max_alertness"] = candidate_public(max_alert, zone) if max_alert["bed"] < best["bed"] else None
    response["partial_reason"] = choice["partial_reason"]
    if choice["partial_reason"] == "unattainable":
        response["message"] = ("연령별 수면시간 범위 안에서는 취침을 앞당겨도 집중할 시간 내내 각성 지표를 0 이상으로 "
                               "유지할 수 없어요(모형). 그래서 연령별 최소 수면시간을 지키는 계획을 보여 드려요.")
    elif choice["partial_reason"] == "large_shift":
        response["message"] = ("모형 조건을 모두 채우려면 하룻밤에 너무 많이 앞당겨야 해요. 오늘은 60분(최소 수면에 더 "
                               "필요하면 그만큼)까지만 앞당기고, 모형 기준 목표 시각은 따로 보여 드려요.")
    if anchor:
        response["alertness_difference"] = round(best["mean_alertness"] - anchor["mean_alertness"], 5)
        response["advance_minutes"] = max(0, round((baseline - deadline["bed"]).total_seconds() / 60))
        # Advance after which necessary sleep ends by the wake time while the age limits also hold.
        necessary = deadlines["necessary"]
        response["necessary_advance_minutes"] = (
            0 if anchor["necessary_ok"] else
            max(0, round((baseline - necessary["bed"]).total_seconds() / 60)) if necessary else None)
        if response["baseline"]["exceeds_recommended"] and choice["mode"] == "keep":
            warnings.append(f"평소 수면시간이 이 연령대 권장 범위({profile['minimum']}~{profile['maximum']}시간)보다 "
                            "길어요. 앱은 줄이라고 권하지 않아요. 충분히 자도 낮에 계속 졸리면 의료 전문가와 상담해 보세요.")

    # Sensitivity of both deadlines to the assumptions (scenario range, not a confidence interval).
    found = {"overall": [], "necessary": []}
    variants = model.variants()
    for variant in variants:
        alt_scenario = scenario if variant is model else Scenario(variant, hist, profile, zone, now, wake, blocks)
        alt = rows if variant is model else [alt_scenario.evaluate(b) for b in beds]
        for key, predicate in (("overall", _complete), ("necessary", lambda r: _hard_ok(r) and r["necessary_ok"])):
            row = _latest(alt, predicate)
            if row:
                found[key].append(row["bed"])
    response["sensitivity"] = {
        "scenarios": len(variants),
        **{f"{key}_{edge}": (iso(fn(values), zone) if values else None)
           for key, values in found.items() for edge, fn in (("earliest", min), ("latest", max))},
        "overall_unresolved": len(variants) - len(found["overall"]),
        "necessary_unresolved": len(variants) - len(found["necessary"])}
    # Moving bedtime much earlier than usual: the model itself says "not sleepy yet" there.
    moving = choice["mode"] in ("advance", "nearest")
    reference = deadline if moving else best
    gap = round(((hist["bed"] - hour(reference["bed"], zone)) % 24) * 60)
    gap = gap if gap < 12 * 60 else 0
    first_row, last_row = choice["window"][0], choice["window"][-1]

    def hm(r):
        return iso(r["bed"], zone)[11:16]

    notes, strong = [], False
    if gap > 60:
        strong = True
        notes.append(f"{'권장 마감' if moving else '이 계획'}({hm(reference)})은 평소 취침(최근 평균)보다 약 {duration_text(gap)} 일러요.")
    if moving and last_row["onset_alertness"] > ONSET_NOTE:
        strong = True
        notes.append(f"모형으로 봐도 권장 마감({hm(last_row)})에는 수면압이 아직 일주기 기준보다 낮아"
                     f"(잠드는 시각의 AL {last_row['onset_alertness']:+.2f}) 바로 잠들기 어려울 수 있어요.")
    elif moving and first_row["onset_alertness"] > ONSET_NOTE:
        notes.append(f"권장 구간의 이른 쪽({hm(first_row)})은 모형상 아직 덜 졸린 때(잠드는 시각의 AL "
                     f"{first_row['onset_alertness']:+.2f})라서, 잠이 오지 않으면 마감({hm(last_row)})에 가깝게 잠들어도 돼요.")
    if strong:
        notes.append("취침 시각은 한 번에 크게 바꾸기보다 매일 밤 15분 이상씩 앞당기고, "
                     "아침 기상도 함께 앞당기는 방법을 권해요.")
    if notes:
        warnings.append(" ".join(notes))

    simulated = sorted(hist["episodes"] + [Episode("__plan", best["bed"], wake, "main")], key=lambda e: e.start)
    compare = anchor is not None and choice["mode"] != "keep"
    start = best["bed"] - timedelta(hours=2)
    local = start.astimezone(zone)  # start the 24-hour chart on a whole local hour
    start -= timedelta(minutes=local.minute, seconds=local.second, microseconds=local.microsecond)
    times = [start + i * STEP for i in range(97)]
    s_plan = pressure_series(times, simulated, model)
    s_base = None
    if compare:
        base_episodes = sorted(hist["episodes"] + [Episode("__baseline", baseline, wake, "main")], key=lambda e: e.start)
        s_base = pressure_series(times, base_episodes, model)
    for i, t in enumerate(times):
        c = scenario.c(t)
        response["chart"].append({
            "at": iso(t, zone), "S": round(s_plan[i], 5), "C": round(c, 5), "AL": round(c - s_plan[i], 5),
            "baseline_AL": round(c - s_base[i], 5) if compare else None,
            "asleep": best["bed"] <= t < wake, "target": any(a <= t < b for a, b in blocks)})
    if target_end > times[-1]:
        warnings.append("집중할 시간의 일부가 24시간 그래프 밖에 있어요. 평균 각성 지표와 후보 비교에는 집중할 시간 전체를 반영했어요.")
    return response


# ------------------------------------------------------------ model A/B/C

def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for i in order[start:end]:
            result[i] = rank
        start = end
    return result


def spearman(a, b):
    if len(a) < 3:
        return None
    a, b = ranks(a), ranks(b)
    ma, mb = mean(a), mean(b)
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if not va or not vb:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def research(payload, now=None):
    now = now or datetime.now(UTC)
    profile, zone, records, observations = validate_dataset(payload, now)
    if not profile["eligible"]:
        return {"status": "tracking_only", "rows": [], "daily": [], "metrics": [],
                "excluded": len(observations),
                "message": "이 연령·생활 유형에는 모형 비교를 제공하지 않아요."}
    model = Model(reference_hours=profile["minimum"])
    starts = [r.start for r in records]   # records are sorted and never overlap,
    ends = [r.end for r in records]       # so both lists are ascending
    pending, excluded = [], 0
    for ob in observations:
        at = ob["at"]
        # Only records finished before the observation are used (no future data);
        # an observation made during recorded sleep is invalid.
        k = bisect_right(starts, at) - 1
        if k >= 0 and records[k].end > at:
            excluded += 1
            continue
        stop = bisect_right(ends, at)
        h = recent_history(records[bisect_left(ends, at - timedelta(days=22)):stop], at, zone, with_episodes=False)
        if h["days"] < 5 or h["stale"] or h["concentration"] < .5:
            excluded += 1
            continue
        past, last = h["mains"][:-1], h["mains"][-1]
        bed, _ = circular([hour(r.start, zone) for r in past])
        wake, _ = circular([hour(r.end, zone) for r in past])
        day_before = at - timedelta(hours=24)
        a = sum(hours_between(max(day_before, r.start), r.end)
                for r in records[bisect_right(ends, day_before):stop])
        b = 1 - (distance(hour(last.start, zone), bed) + distance(hour(last.end, zone), wake)) / 24
        pending.append({"ob": ob, "h": h, "A": a, "B": b})
    # S at each observation: one forward pass per history block (same start => same S path).
    groups = {}
    for item in pending:
        groups.setdefault(item["h"]["mains"][0].start, []).append(item)
    for block_start, items in groups.items():
        last_at = items[-1]["ob"]["at"]
        episodes = records[bisect_left(starts, block_start):bisect_right(ends, last_at)]
        for item, s in zip(items, pressure_series([it["ob"]["at"] for it in items], episodes, model)):
            item["S"] = s
    rows = []
    for item in pending:
        at, h = item["ob"]["at"], item["h"]
        c = threshold(at, h["trough"], zone, model) - item["S"]
        rows.append({"at": iso(at, zone), "sleepiness": item["ob"]["sleepiness"], "A": round(item["A"], 6),
                     "B": round(item["B"], 6), "C": round(c, 6), "history_days": h["days"]})
    groups = {}
    for row in rows:  # one value per day: repeated reports are not independent
        groups.setdefault(row["at"][:10], []).append(row)
    daily = [{"date": day, **{k: mean(r[k] for r in rr) for k in ("sleepiness", "A", "B", "C")}, "n": len(rr)}
             for day, rr in sorted(groups.items())]
    metrics = []
    for k in ("A", "B", "C"):
        rho = spearman([r[k] for r in daily], [-r["sleepiness"] for r in daily]) if len(daily) >= 5 else None
        metrics.append({"model": k, "rho_with_alertness": round(rho, 4) if rho is not None else None,
                        "days": len(daily)})
    return {"status": "ready" if len(daily) >= 5 else "insufficient", "rows": rows, "daily": daily,
            "metrics": metrics, "excluded": excluded,
            "message": "같은 날의 기록은 평균해 하루 한 값으로 비교해요. 값은 각 모형과 ‘졸리지 않음’(-졸림)의 Spearman 순위상관이고, 임상 정확도·인과 효과·미래 예측 성능을 뜻하지 않아요. 각 시각보다 앞선 기록만 쓴 사후 비교예요."}


def summary(payload, now=None):
    now = now or datetime.now(UTC)
    profile, zone, records, observations = validate_dataset(payload, now)
    h = recent_history(records, now, zone)
    mains = h["mains"]
    last24 = sum(max(0.0, hours_between(max(now - timedelta(hours=24), r.start), min(now, r.end)))
                 for r in records if r.end > now - timedelta(hours=24))
    return {"profile": profile, "record_count": len(records), "observation_count": len(observations),
            "history_days": h["days"],
            "mean_main_hours": round(mean(r.hours for r in mains), 2) if mains else None,
            "last24_hours": round(last24, 2), "habitual_bed_hour": h["bed"], "habitual_wake_hour": h["wake"],
            "phase_concentration": h["concentration"], "stale": h["stale"],
            "duplicate_day": h["duplicate_day"], "model_version": VERSION}
