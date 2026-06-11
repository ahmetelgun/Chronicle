"""Custom filters used in templates."""
from django import template

register = template.Library()


# Status -> Bulma color class mapping (for tag/button colors).
_STATUS_CLASS = {
    "SUCCESS": "is-success",
    "FAILED": "is-danger",
    "TIMEOUT": "is-warning",
    "ERROR": "is-danger",
    "RUNNING": "is-info",
    "ABORTED": "is-warning",
}

# Log line level -> Bulma color class (log detail view).
_LEVEL_CLASS = {
    "ERROR": "is-danger",
    "ERR": "is-danger",
    "WARN": "is-warning",
    "INFO": "is-light",
    "EVENT": "is-info",
    "METRIC": "is-link",
    "OUT": "is-light",
}


@register.filter
def level_class(level: str) -> str:
    """Bulma color class corresponding to the log line level."""
    return _LEVEL_CLASS.get((level or "").upper(), "is-light")


@register.filter
def status_class(status: str) -> str:
    """Returns the Bulma color class corresponding to the execution status."""
    return _STATUS_CLASS.get(status, "is-light")


# Event category -> Bulma color class. Known severities get a specific color;
# other (custom) categories are shown in the neutral 'is-info' tone.
_EVENT_CLASS = {
    "error": "is-danger",
    "warning": "is-warning",
    "info": "is-light",
}


@register.filter
def event_class(category: str) -> str:
    """Returns the Bulma color class corresponding to the event category."""
    return _EVENT_CLASS.get((category or "").lower(), "is-info")


@register.filter
def duration_human(seconds) -> str:
    """Converts seconds to a human-readable duration (e.g. 1m 23s)."""
    if seconds is None:
        return "—"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{sec}s")
    return " ".join(parts)
