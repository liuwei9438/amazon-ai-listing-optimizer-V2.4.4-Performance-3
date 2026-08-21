from __future__ import annotations
import re
from typing import Any


class TitleBudgetComposer:
    """
    Stable Title Pipeline V1.0: deterministic 75-char budget.
    Uses only full_text or AI-supplied complete short_text.
    """

    VERSION = "stable-v1.0-budget-composer"
    MIN_TARGET = 61
    MAX_LENGTH = 75

    @staticmethod
    def _clean(v: Any) -> str:
        return re.sub(r"\s+", " ", str(v or "")).strip()

    @staticmethod
    def _join(parts: list[str]) -> str:
        return TitleBudgetComposer._clean(" ".join(x for x in parts if x))

    @staticmethod
    def _variant(fact: dict, parts: list[str]) -> str:
        full = TitleBudgetComposer._clean(fact.get("full_text"))
        short = TitleBudgetComposer._clean(fact.get("short_text"))
        for text in [full, short]:
            if not text:
                continue
            if text.casefold() in TitleBudgetComposer._join(parts).casefold():
                continue
            if len(TitleBudgetComposer._join(parts + [text])) <= TitleBudgetComposer.MAX_LENGTH:
                return text
        return ""

    @staticmethod
    def compose(plan: dict) -> dict:
        facts = plan.get("facts", [])
        facts = facts if isinstance(facts, list) else []

        required = [x for x in facts if isinstance(x, dict) and x.get("required")]
        optional = [x for x in facts if isinstance(x, dict) and not x.get("required")]

        parts, used, rejected = [], [], []

        # Required facts first. If they cannot coexist, fail closed.
        for fact in required:
            chosen = TitleBudgetComposer._variant(fact, parts)
            if not chosen:
                rejected.append({**fact, "reason": "REQUIRED_CORE_OVERFLOW"})
                return {
                    "version": TitleBudgetComposer.VERSION,
                    "title": "",
                    "status": "TITLE_BUDGET_CONFLICT",
                    "used_facts": used,
                    "rejected_facts": rejected,
                    "character_count": 0,
                }
            parts.append(chosen)
            used.append({**fact, "selected_text": chosen})

        # Optional facts are already ranked by planner.
        for fact in optional:
            chosen = TitleBudgetComposer._variant(fact, parts)
            if chosen:
                parts.append(chosen)
                used.append({**fact, "selected_text": chosen})
            else:
                rejected.append({**fact, "reason": "CHARACTER_BUDGET"})

        title = TitleBudgetComposer._join(parts)

        # If under 61, make a second pass over rejected facts in the same
        # priority order. This never invents/crops text.
        if len(title) < TitleBudgetComposer.MIN_TARGET:
            still_rejected = []
            for fact in rejected:
                if fact.get("reason") != "CHARACTER_BUDGET":
                    still_rejected.append(fact)
                    continue
                chosen = TitleBudgetComposer._variant(fact, parts)
                if chosen:
                    parts.append(chosen)
                    used.append({**fact, "selected_text": chosen})
                    title = TitleBudgetComposer._join(parts)
                else:
                    still_rejected.append(fact)
                if len(title) >= TitleBudgetComposer.MIN_TARGET:
                    still_rejected.extend(
                        x for x in rejected
                        if x not in still_rejected and x.get("fact_id") not in {u.get("fact_id") for u in used}
                    )
                    break
            rejected = still_rejected

        title = TitleBudgetComposer._join(parts)

        status = "READY"
        if len(title) > TitleBudgetComposer.MAX_LENGTH:
            status = "TITLE_BUDGET_CONFLICT"
        elif len(title) < TitleBudgetComposer.MIN_TARGET:
            remaining = [
                x for x in rejected
                if x.get("reason") == "CHARACTER_BUDGET"
            ]
            status = (
                "TITLE_COMPOSITION_FAILED"
                if remaining
                else
                "SOURCE_FACTS_INSUFFICIENT"
            )

        return {
            "version": TitleBudgetComposer.VERSION,
            "title": title,
            "status": status,
            "used_facts": used,
            "rejected_facts": rejected,
            "character_count": len(title),
            "budget_remaining": max(0, 75 - len(title)),
        }
