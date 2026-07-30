import os
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured


def get_from_env(
    key: str,
    default: Any = None,
    *,
    optional: bool = False,
    type_cast: Callable | None = None,
    allowed_values: set | None = None,
) -> Any:
    value = os.getenv(key)
    if value is not None:
        value = value.strip().strip('"').strip("'")
    if value is None or value == "":
        if optional:
            return None
        if default is not None:
            value = default
        else:
            raise ImproperlyConfigured(f'The environment variable "{key}" is required to run Project!')
    if type_cast is not None:
        value = type_cast(value)
    if allowed_values is not None and value not in allowed_values:
        raise ImproperlyConfigured(
            f'The value "{value}" for environment variable "{key}" is not allowed. Allowed values are: {allowed_values}'
        )
    return value


def get_set(text: str) -> set[str]:
    if not text:
        return set()
    return {item.strip() for item in text.split(",")}


def str_to_bool(s: str | bool) -> bool:
    if isinstance(s, bool):
        return s
    return s.lower() in {"true", "yes", "1"}
