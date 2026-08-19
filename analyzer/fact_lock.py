from __future__ import annotations

import re
from typing import Any


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"\s*\|\s*|\n+|;\s*", str(value))
    output: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _clean(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _source_text(record: Any) -> str:
    values: list[str] = []
    for name in (
        "title", "description", "details", "color", "variant",
        "quantity", "material", "dimensions", "voltage", "power",
    ):
        values.append(_clean(getattr(record, name, "")))
    values.extend(_list(getattr(record, "bullets", [])))
    return " ".join(x for x in values if x)


def _first_supported(record: Any, *names: str) -> str:
    source = _source_text(record).casefold()
    for name in names:
        value = _clean(getattr(record, name, ""))
        if value and value.casefold() in source:
            return value
    return ""


def _extract_models(text: str) -> list[str]:
    candidates = re.findall(
        r"\b(?=[A-Za-z0-9-]{2,24}\b)(?=[A-Za-z0-9-]*\d)"
        r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b",
        text,
    )
    blocked = {"100", "120", "1600", "220", "240", "2024", "2025", "2026"}
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        key = value.casefold()
        if value not in blocked and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def build_fact_lock(record: Any) -> dict[str, Any]:
    source = _source_text(record)
    package_contents = _list(getattr(record, "package_contents", []))
    part_numbers = _list(getattr(record, "part_numbers", []))
    explicit_models = _list(
        getattr(record, "compatible_models", [])
        or getattr(record, "models", [])
    )
    detected_models = _extract_models(source)

    models: list[str] = []
    seen: set[str] = set()
    for value in [*explicit_models, *detected_models]:
        key = value.casefold()
        if value and value.casefold() in source.casefold() and key not in seen:
            seen.add(key)
            models.append(value)

    return {
        "quantity": _first_supported(record, "quantity"),
        "material": _first_supported(record, "material"),
        "color": _first_supported(record, "color"),
        "dimensions": _first_supported(record, "dimensions"),
        "voltage": _first_supported(record, "voltage"),
        "power": _first_supported(record, "power"),
        "compatible_models": models,
        "part_numbers": [
            value for value in part_numbers
            if value.casefold() in source.casefold()
        ],
        "package_contents": [
            value for value in package_contents
            if value.casefold() in source.casefold()
        ],
    }


def validate_fact_lock(
    profile: dict[str, Any],
    expected_lock: dict[str, Any],
) -> list[str]:
    actual = profile.get("fact_lock")
    if actual != expected_lock:
        return ["事实锁与原始数据不一致"]
    return []
