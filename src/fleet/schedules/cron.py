"""Five-field cron parsing and next-firing math (pure, no I/O).

Called by `model.py` (template validation) and, later, the supervisor's
scheduler service. All zone handling goes through `zoneinfo.ZoneInfo`;
unknown zones raise `CronError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MAX_ITERATIONS = 200_000
_MAX_UPCOMING = 50
_FIELD_COUNT = 5
_DECEMBER = 12
_SUNDAY_ALT = 7  # cron accepts 7 as a second spelling of Sunday

_ALIASES: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

_MONTH_NAMES: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_WEEKDAY_NAMES: dict[str, int] = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}

# (field name, minimum, maximum) in cron-field order.
_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 7),
)


class CronError(ValueError):
    """A cron expression, field value, or time zone fleet cannot use."""


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """One parsed 5-field cron expression (minutes, hours, days, months, weekdays)."""

    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: tuple[int, ...]
    months: tuple[int, ...]
    weekdays: tuple[int, ...]
    day_restricted: bool
    weekday_restricted: bool

    def matches(self, moment: datetime) -> bool:
        """True when this schedule fires at the minute `moment` falls in."""
        if moment.minute not in self.minutes:
            return False
        if moment.hour not in self.hours:
            return False
        if moment.month not in self.months:
            return False
        return _day_matches(self, moment.day, _cron_weekday(moment))


def _day_matches(schedule: CronSchedule, day: int, weekday: int) -> bool:
    """Day match with Vixie cron OR semantics for day/weekday."""
    dom = day in schedule.days
    dow = weekday in schedule.weekdays
    if schedule.day_restricted and schedule.weekday_restricted:
        return dom or dow
    if schedule.day_restricted:
        return dom
    if schedule.weekday_restricted:
        return dow
    return True


def _cron_weekday(moment: datetime) -> int:
    """Weekday as cron sees it: Monday=1 .. Saturday=6, Sunday=0."""
    return moment.isoweekday() % 7


def _resolve_names(token: str, field: str) -> str:
    """Replace month/weekday names in one comma-free token with numbers."""
    table = _MONTH_NAMES if field == "month" else _WEEKDAY_NAMES if field == "weekday" else None
    if table is None:
        return token
    out = token
    for name, number in table.items():
        out = _replace_name(out, name, str(number))
    return out


def _replace_name(token: str, name: str, number: str) -> str:
    """Replace `name` in `token` only when it is not part of a longer word."""
    lowered = token.lower()
    parts: list[str] = []
    i = 0
    while i < len(token):
        if lowered.startswith(name, i):
            before = token[i - 1] if i > 0 else ""
            end = i + len(name)
            after = token[end] if end < len(token) else ""
            if not before.isalpha() and not after.isalpha():
                parts.append(number)
                i = end
                continue
        parts.append(token[i])
        i += 1
    return "".join(parts)


def _parse_value(raw: str, field: str, minimum: int, maximum: int) -> int:
    """Parse one integer literal, naming the field on failure."""
    try:
        value = int(raw, 10)
    except ValueError:
        raise CronError(f"{field}: {raw!r} is not a number or known name") from None
    if not minimum <= value <= maximum:
        raise CronError(f"{field}: {value} is outside {minimum}-{maximum}")
    return value


def _expand_part(part: str, field: str, minimum: int, maximum: int) -> set[int]:
    """Expand one comma-free `base[/step]` token to a set of values."""
    if "/" in part:
        base, _, step_raw = part.partition("/")
        try:
            step = int(step_raw, 10)
        except ValueError:
            raise CronError(f"{field}: bad step {step_raw!r}") from None
        if step < 1:
            raise CronError(f"{field}: step must be >= 1, got {step}")
    else:
        base, step = part, 1
    if base == "*":
        low, high = minimum, maximum
    elif "-" in base:
        start_raw, _, end_raw = base.partition("-")
        low = _parse_value(start_raw, field, minimum, maximum)
        high = _parse_value(end_raw, field, minimum, maximum)
        if low > high:
            raise CronError(f"{field}: range {low}-{high} is backwards")
    elif base == "":
        raise CronError(f"{field}: empty value in {part!r}")
    else:
        low = _parse_value(base, field, minimum, maximum)
        high = maximum if "/" in part else low
    return set(range(low, high + 1, step))


def _parse_field(raw: str, field: str, minimum: int, maximum: int) -> tuple[int, ...]:
    """Parse one cron field (comma list) to a sorted value tuple."""
    if raw == "":
        raise CronError(f"{field}: empty field")
    values: set[int] = set()
    for part in raw.split(","):
        token = _resolve_names(part.strip(), field)
        if token == "":
            raise CronError(f"{field}: empty value in {raw!r}")
        values |= _expand_part(token, field, minimum, maximum)
    if field == "weekday" and _SUNDAY_ALT in values:
        values.discard(_SUNDAY_ALT)
        values.add(0)
    if not values:
        raise CronError(f"{field}: {raw!r} selects no values")
    return tuple(sorted(values))


def parse(expr: str) -> CronSchedule:
    """Parse a 5-field cron expression (or @alias) to a `CronSchedule`."""
    text = expr.strip().lower()
    text = _ALIASES.get(text, text)
    parts = text.split()
    if len(parts) != _FIELD_COUNT:
        raise CronError(f"expression: expected 5 fields, got {len(parts)} in {expr!r}")
    parsed = [
        _parse_field(raw, name, low, high)
        for raw, (name, low, high) in zip(parts, _FIELDS, strict=True)
    ]
    return CronSchedule(
        minutes=parsed[0],
        hours=parsed[1],
        days=parsed[2],
        months=parsed[3],
        weekdays=parsed[4],
        day_restricted=parts[2] != "*",
        weekday_restricted=parts[4] != "*",
    )


def _zone(tz: str) -> ZoneInfo:
    """Return the zone, raising `CronError` for unknown names."""
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise CronError(f"timezone: unknown zone {tz!r}") from None


def zone(tz: str) -> ZoneInfo:
    """Return the `ZoneInfo` for `tz`, raising `CronError` when unknown."""
    return _zone(tz)


def _step(cur: datetime, schedule: CronSchedule) -> datetime:
    """Advance one wall-clock step toward the next firing minute."""
    if cur.month not in schedule.months:
        year, month = (cur.year + 1, 1) if cur.month == _DECEMBER else (cur.year, cur.month + 1)
        return cur.replace(year=year, month=month, day=1, hour=0, minute=0)
    if not _day_matches(schedule, cur.day, _cron_weekday(cur)):
        return (cur + timedelta(days=1)).replace(hour=0, minute=0)
    if cur.hour not in schedule.hours:
        return cur.replace(minute=0) + timedelta(hours=1)
    if cur.minute not in schedule.minutes:
        return cur + timedelta(minutes=1)
    return cur


def next_fire(expr: str | CronSchedule, after: datetime, tz: str = "UTC") -> datetime:
    """First firing minute strictly after `after`, as aware UTC."""
    schedule = parse(expr) if isinstance(expr, str) else expr
    zone = _zone(tz)
    base = after if after.tzinfo is not None else after.replace(tzinfo=UTC)
    cur = base.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MAX_ITERATIONS):
        advanced = _step(cur, schedule)
        if advanced is cur or (
            advanced.year == cur.year
            and advanced.month == cur.month
            and advanced.day == cur.day
            and advanced.hour == cur.hour
            and advanced.minute == cur.minute
        ):
            return cur.astimezone(UTC)
        cur = advanced
    raise CronError(f"expression: no firing found within {_MAX_ITERATIONS} steps")


def upcoming(expr: str, after: datetime, count: int = 5, tz: str = "UTC") -> list[datetime]:
    """Next `count` firing minutes after `after` (count capped at 50)."""
    schedule = parse(expr)
    wanted = max(0, min(count, _MAX_UPCOMING))
    out: list[datetime] = []
    cursor = after
    for _ in range(wanted):
        cursor = next_fire(schedule, cursor, tz)
        out.append(cursor)
    return out
