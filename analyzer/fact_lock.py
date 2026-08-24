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
        "title",
        "description",
        "details",
        "color",
        "variant",
        "quantity",
        "material",
        "dimensions",
        "voltage",
        "power",
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


def _is_obvious_non_model(value: str) -> bool:
    v = _clean(value)
    if not v:
        return True

    low = v.casefold()

    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:pcs?|pieces?|sets?|packs?|pairs?)", low):
        return True

    if re.fullmatch(
        r"\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?){0,3}\s*"
        r"(?:mm|cm|m|in|inch|inches|ft)?",
        low,
    ):
        if re.search(r"[x×]|(?:mm|cm|m|in|inch|inches|ft)$", low):
            return True

    if re.fullmatch(
        r"\d+(?:\.\d+)?\s*"
        r"(?:v|w|kw|mw|a|ma|hz|khz|mhz|ghz|mah|ah|wh|kwh|"
        r"g|kg|mg|lb|lbs|oz|ml|l|bar|psi|pa|kpa|mpa|rpm|°c|°f)",
        low,
    ):
        return True

    if re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?\s*k(?:\s*ohms?)?", low):
        return True

    if re.fullmatch(r"\d+\s*[- ]?(?:wire|wires|conductor|conductors)", low):
        return True

    if re.fullmatch(
        r"\d+\s*[- ]?(?:pin|pins|pole|poles|speed|speeds|stage|stages|"
        r"gear|gears|blade|blades|tooth|teeth)",
        low,
    ):
        return True

    if re.fullmatch(r"(?:19|20)\d{2}", low):
        return True

    return False


def _numeric_model_context(text: str, value: str, start: int, end: int) -> bool:
    # Long pure-numeric codes are commonly part/model numbers.
    # Keep them unless another semantic rule already rejected them.
    if value.isdigit() and len(value) >= 7:
        return True

    left = text[max(0, start - 80):start]
    right = text[end:min(len(text), end + 80)]
    context = f"{left} {right}".casefold()

    positive_cues = (
        "model",
        "models",
        "compatible",
        "compatibility",
        "suitable for",
        "fit for",
        "fits",
        "replacement for",
        "for chainsaw",
        "for mower",
        "for projector",
        "for printer",
        "for scooter",
        "for vacuum",
        "for machine",
        "for equipment",
    )

    if any(cue in context for cue in positive_cues):
        return True

    window_start = max(0, start - 120)
    window_end = min(len(text), end + 120)
    window = text[window_start:window_end]
    nums = re.findall(r"(?<![\w.])\d{3,6}(?![\w.])", window)

    if len(nums) >= 3:
        prefix = text[max(0, start - 140):start].casefold()
        if re.search(r"\b(?:for|suitable\s+for|compatible\s+with|fits?)\b", prefix):
            return True

    return False


def _extract_models(text: str) -> list[str]:
    source = _clean(text)
    if not source:
        return []

    pattern = re.compile(
        r"(?<![A-Za-z0-9])"
        r"(?=[A-Za-z0-9._/+\-]{2,40}(?![A-Za-z0-9._/+\-]))"
        r"(?=[A-Za-z0-9._/+\-]*\d)"
        r"[A-Za-z0-9]+(?:[._/+\-][A-Za-z0-9]+)*"
        r"(?![A-Za-z0-9])"
    )

    result: list[str] = []
    seen: set[str] = set()

    for match in pattern.finditer(source):
        value = match.group(0).strip(".,;:")
        if not value:
            continue

        if _is_obvious_non_model(value):
            continue

        if value.isdigit() and not _numeric_model_context(
            source,
            value,
            match.start(),
            match.end(),
        ):
            continue

        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)

    return result


def build_fact_lock(record: Any) -> dict[str, Any]:
    source = _source_text(record)
    source_cf = source.casefold()

    package_contents = _list(getattr(record, "package_contents", []))
    part_numbers = _list(getattr(record, "part_numbers", []))

    explicit_models = _list(
        getattr(record, "compatible_models", [])
        or getattr(record, "models", [])
    )

    explicit_models = [
        value
        for value in explicit_models
        if value.casefold() in source_cf and not _is_obvious_non_model(value)
    ]

    detected_models = _extract_models(source)

    models: list[str] = []
    seen: set[str] = set()

    for value in [*explicit_models, *detected_models]:
        key = value.casefold()
        if value and value.casefold() in source_cf and key not in seen:
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
            if value.casefold() in source_cf
        ],
        "package_contents": [
            value for value in package_contents
            if value.casefold() in source_cf
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
