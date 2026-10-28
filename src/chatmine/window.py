"""Janela de tempo de uma consulta (extract e search)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

DEFAULT_DAYS = 7.0
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parse(value: str, flag: str, *, end_of_day: bool = False) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{flag}: data inválida {value!r}; use ISO 8601") from None
    if end_of_day and _DATE_ONLY.fullmatch(value):
        dt += timedelta(days=1, microseconds=-1)
    # Sem fuso, `astimezone()` assume o fuso local da máquina.
    return dt.astimezone()


def resolve_window(
    since: str | None, until: str | None, days: float | None, now: datetime
) -> tuple[datetime, datetime]:
    """Resolve (início, fim) de --since/--until/--days; ValueError em uso inválido."""
    if since and days is not None:
        raise ValueError("--since e --days não podem ser usados juntos")
    end = _parse(until, "--until", end_of_day=True) if until else now
    back = timedelta(days=DEFAULT_DAYS if days is None else days)
    start = _parse(since, "--since") if since else end - back
    if end < start:
        raise ValueError("--until é anterior a --since")
    return start, end
