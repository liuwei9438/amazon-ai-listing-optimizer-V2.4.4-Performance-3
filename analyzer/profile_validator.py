from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .product_profile_schema import empty_profile


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _merge(default: Any, incoming: Any) -> Any:
    if isinstance(default, dict):
        source = incoming if isinstance(incoming, dict) else {}
        return {
            key: _merge(value, source.get(key))
            for key, value in default.items()
        }
    if isinstance(default, list):
        return _list(incoming)
    if isinstance(default, bool):
        return incoming if isinstance(incoming, bool) else default
    if isinstance(default, int):
        try:
            return int(incoming)
        except (TypeError, ValueError):
            return default
    return _clean(incoming)


def normalize_profile(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    profile = _merge(empty_profile(), source)

    if profile["brand_info"]["relationship"] not in {
        "unbranded_compatible",
        "own_brand",
        "generic",
        "high_risk_brand_usage",
        "unknown",
    }:
        profile["brand_info"]["relationship"] = "unknown"

    if profile["brand_info"]["risk_level"] not in {"low", "medium", "high"}:
        profile["brand_info"]["risk_level"] = "low"

    if profile["brand_info"]["rewrite_strategy"] not in {
        "compatible_with", "own_brand", "no_brand"
    }:
        profile["brand_info"]["rewrite_strategy"] = "no_brand"

    if profile["compliance"]["risk_level"] not in {"low", "medium", "high"}:
        profile["compliance"]["risk_level"] = "low"

    return profile


def validate_profile(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_sections = set(empty_profile())
    missing_sections = required_sections - set(profile)
    if missing_sections:
        errors.append("缺少 Product Profile 模块：" + "、".join(sorted(missing_sections)))

    basic = profile.get("basic_info", {})
    if not isinstance(basic, dict):
        errors.append("basic_info 格式错误")
    elif not _clean(basic.get("product_type")):
        errors.append("未识别产品类型")

    for section, field in (
        ("compatibility", "brands"),
        ("compatibility", "models"),
        ("seo", "main_keywords"),
    ):
        value = profile.get(section, {}).get(field, [])
        if not isinstance(value, list):
            errors.append(f"{section}.{field} 必须是数组")

    return errors
