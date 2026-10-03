"""Cron scheduling and time calculation engine for AURA automations."""

import zoneinfo
from datetime import datetime, timezone
from typing import List, Optional
from croniter import croniter
from app.core.errors import ValidationError


def validate_cron_expression(cron_expression: str) -> None:
    """Validate that the expression is a valid 5-field cron format."""
    clean = cron_expression.strip()
    parts = clean.split()
    if len(parts) != 5:
        raise ValidationError(
            f"Cron expression must contain exactly 5 fields ('minute hour day month day-of-week'), received {len(parts)}"
        )
    if not croniter.is_valid(clean):
        raise ValidationError(f"Invalid cron expression: '{clean}'")


def get_zoneinfo(timezone_str: str) -> zoneinfo.ZoneInfo:
    """Safely obtain ZoneInfo instance from timezone string."""
    try:
        return zoneinfo.ZoneInfo(timezone_str.strip())
    except Exception as e:
        raise ValidationError(f"Invalid timezone identifier '{timezone_str}': {e}") from e


def calculate_next_run(
    cron_expression: str,
    base_time: Optional[datetime] = None,
    timezone_str: str = "UTC",
) -> datetime:
    """Calculate the next scheduled execution time in UTC given a cron expression and timezone.

    Always returns a timezone-aware UTC datetime.
    """
    validate_cron_expression(cron_expression)
    tz = get_zoneinfo(timezone_str)

    if base_time is None:
        base_time = datetime.now(timezone.utc)
    elif base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=timezone.utc)

    # Convert base time to target timezone for localized cron calculation
    localized_base = base_time.astimezone(tz)
    
    # croniter calculates using the localized base datetime
    iter_obj = croniter(cron_expression.strip(), localized_base)
    next_local_dt = iter_obj.get_next(datetime)

    # Ensure localized timezone attached if naive
    if next_local_dt.tzinfo is None:
        next_local_dt = next_local_dt.replace(tzinfo=tz)

    # Convert to canonical UTC
    return next_local_dt.astimezone(timezone.utc)


def resolve_due_schedule(
    cron_expression: str,
    last_run_at: Optional[datetime],
    next_run_at: Optional[datetime],
    now: datetime,
    timezone_str: str = "UTC",
) -> datetime:
    """Determine the next scheduled timestamp enforcing AURA's bounded missed-run policy.

    Prevents unbounded execution backlogs when restarting after prolonged downtime.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Calculate next execution strictly starting from current moment
    return calculate_next_run(cron_expression, base_time=now, timezone_str=timezone_str)
