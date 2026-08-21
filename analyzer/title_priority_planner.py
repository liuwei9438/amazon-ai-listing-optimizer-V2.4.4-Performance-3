from __future__ import annotations
from typing import Any


class TitlePriorityPlanner:
    """Stable Title Pipeline V1.0: rank approved facts; never compose title."""

    VERSION = "stable-v1.0-priority-planner"
    TYPE_ORDER = {
        "QUANTITY": 0, "IDENTITY": 1, "COMPATIBILITY_BRAND": 2,
        "MODEL": 3, "PART_NUMBER": 3, "COMPATIBILITY_MODEL": 4,
        "SECONDARY_IDENTITY": 5, "SPECIFICATION": 6,
        "CONTEXT": 7, "SOURCE_CONTEXT": 7, "FEATURE": 8,
        "MATERIAL": 9, "COLOR": 10, "SEARCH_TERM": 11,
    }

    @staticmethod
    def _clean(v: Any) -> str:
        return " ".join(str(v or "").split())

    @staticmethod
    def build(resolved_facts: dict, ai_plan: dict | None = None, target_language="English") -> dict:
        facts = resolved_facts.get("approved_facts", [])
        facts = facts if isinstance(facts, list) else []
        ai_plan = ai_plan if isinstance(ai_plan, dict) else {}

        ai_map = {}
        for item in ai_plan.get("fact_priorities", []) or []:
            if isinstance(item, dict):
                fid = TitlePriorityPlanner._clean(item.get("fact_id"))
                if fid:
                    ai_map[fid] = item

        out = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            fid = TitlePriorityPlanner._clean(fact.get("fact_id"))
            full = TitlePriorityPlanner._clean(fact.get("text"))
            if not fid or not full:
                continue

            ai = ai_map.get(fid, {})
            short = TitlePriorityPlanner._clean(ai.get("short_text"))
            try:
                value = float(ai.get("value_score", fact.get("priority", 0)))
            except Exception:
                value = float(fact.get("priority", 0) or 0)

            out.append({
                **fact,
                "full_text": full,
                "short_text": short,
                "value_score": value,
                "language": target_language,
                "ai_reason": TitlePriorityPlanner._clean(ai.get("reason")),
            })

        out.sort(key=lambda x: (
            0 if x.get("required") else 1,
            TitlePriorityPlanner.TYPE_ORDER.get(x.get("type"), 99),
            -float(x.get("value_score", 0)),
            len(x.get("full_text", "")),
        ))

        return {
            "version": TitlePriorityPlanner.VERSION,
            "target_language": target_language,
            "facts": out,
        }
