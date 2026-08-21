from __future__ import annotations
import re
from typing import Any


class TitleFactResolver:
    """Stable Title Pipeline V1.0: source-backed fact resolver only."""

    VERSION = "stable-v1.0-fact-resolver"
    STRICT_TYPES = {
        "MODEL", "PART_NUMBER", "COMPATIBILITY_MODEL",
        "COMPATIBILITY_BRAND", "SPECIFICATION",
    }
    MARKETING = {
        "wholesale", "best seller", "#1", "premium", "original",
        "genuine", "official", "authentic", "oem", "hot sale",
        "high quality", "high-quality",
    }
    NOISE = [
        r"\bplease\s+allow\b",
        r"\bmeasurement\s+(?:allowed\s+)?error\b",
        r"\bmanual\s+measurement\b",
        r"\bdue\s+to\s+manual\b",
        r"\bslightly\s+different\b",
        r"\bmainland\s+china\b",
        r"\b\d+\.(?:please|the|technical|note)\b",
    ]

    @staticmethod
    def _clean(v: Any) -> str:
        return re.sub(r"\s+", " ", str(v or "")).strip()

    @staticmethod
    def _flatten(v: Any) -> list[str]:
        out = []
        if isinstance(v, str):
            t = TitleFactResolver._clean(v)
            if t:
                out.append(t)
        elif isinstance(v, dict):
            for x in v.values():
                out.extend(TitleFactResolver._flatten(x))
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                out.extend(TitleFactResolver._flatten(x))
        return out

    @staticmethod
    def _source_text(profile: dict) -> str:
        ledger = profile.get("source_fact_ledger", {})
        ledger = ledger if isinstance(ledger, dict) else {}
        snap = ledger.get("source_snapshot", {})
        snap = snap if isinstance(snap, dict) else {}
        parts = [
            TitleFactResolver._clean(snap.get("title")),
            *TitleFactResolver._flatten(snap.get("bullets", [])),
            TitleFactResolver._clean(snap.get("description")),
            *TitleFactResolver._flatten(ledger.get("raw_fields", {})),
        ]
        return " ".join(x for x in parts if x)

    @staticmethod
    def _quantity(v: Any) -> str:
        m = re.search(
            r"\b(\d{1,4})\s*(?:pcs?|pieces?|piece|sets?)\b",
            TitleFactResolver._clean(v),
            flags=re.I,
        )
        if not m:
            return ""
        n = int(m.group(1))
        return "" if n <= 1 else f"{n}pcs"

    @staticmethod
    def resolve(profile: dict) -> dict:
        profile = profile if isinstance(profile, dict) else {}
        source = TitleFactResolver._source_text(profile)
        si = profile.get("title_strategy_input", {})
        si = si if isinstance(si, dict) else {}
        locked = si.get("locked", {})
        locked = locked if isinstance(locked, dict) else {}
        compat = si.get("compatibility_facts", {})
        compat = compat if isinstance(compat, dict) else {}
        cf = si.get("candidate_facts", {})
        cf = cf if isinstance(cf, dict) else {}
        se = si.get("source_evidence", {})
        se = se if isinstance(se, dict) else {}

        approved, rejected, seen = [], [], set()
        seq = 1

        def add(text, typ, priority, required=False, source_key="", trace=None):
            nonlocal seq
            text = TitleFactResolver._clean(text)
            if not text:
                return
            key = (typ, text.casefold())
            if key in seen:
                return
            seen.add(key)

            if trace is None:
                trace = typ in TitleFactResolver.STRICT_TYPES
            traceable = (not trace) or text.casefold() in source.casefold()
            marketing = any(x in text.casefold() for x in TitleFactResolver.MARKETING)
            noisy = False
            if typ == "SPECIFICATION":
                for pattern in TitleFactResolver.NOISE:
                    for m in re.finditer(pattern, source, flags=re.I):
                        window = source[max(0, m.start()-100):min(len(source), m.end()+140)]
                        if text.casefold() in window.casefold():
                            noisy = True
                            break
                    if noisy:
                        break

            row = {
                "fact_id": f"F{seq:03d}", "text": text, "type": typ,
                "priority": int(priority), "required": bool(required),
                "source_key": source_key, "source_traceable": bool(traceable),
            }
            seq += 1

            if not traceable:
                row["rejection_reason"] = "NOT_TRACEABLE_TO_SOURCE"
                rejected.append(row)
            elif noisy:
                row["rejection_reason"] = "SOURCE_NOISE"
                rejected.append(row)
            elif marketing:
                row["rejection_reason"] = "MARKETING_TERM"
                rejected.append(row)
            else:
                approved.append(row)

        q = TitleFactResolver._quantity(cf.get("important_quantity"))
        if not q:
            qs = se.get("quantities", [])
            if isinstance(qs, list) and qs:
                q = TitleFactResolver._quantity(qs[0])
        if q:
            add(q, "QUANTITY", 100, True, "quantity", False)

        identity = locked.get("identity", {})
        if isinstance(identity, dict):
            add(identity.get("text"), "IDENTITY", 95, True, "locked.identity.text", False)

        for brand in compat.get("brands", []) or []:
            add(brand, "COMPATIBILITY_BRAND", 90, True, "compatibility_facts.brands")

        models = locked.get("models", {})
        if isinstance(models, dict):
            primary = TitleFactResolver._clean(models.get("primary"))
            if primary:
                add(primary, "MODEL", 85, True, "locked.models.primary")
            for x in models.get("secondary", []) or []:
                add(x, "MODEL", 78, False, "locked.models.secondary")
            for x in models.get("all", []) or []:
                add(x, "MODEL", 72, False, "locked.models.all")

        for x in compat.get("models", []) or []:
            add(x, "COMPATIBILITY_MODEL", 80, False, "compatibility_facts.models")
        for x in compat.get("part_numbers", []) or []:
            add(x, "PART_NUMBER", 82, False, "compatibility_facts.part_numbers")
        for x in compat.get("important_compatibility", []) or []:
            t = TitleFactResolver._clean(x)
            if re.fullmatch(r"[A-Za-z0-9._/+*-]+", t):
                add(t, "COMPATIBILITY_MODEL", 74, False, "compatibility_facts.important_compatibility")

        for field in ("source_specifications", "important_specifications", "specifications"):
            for x in cf.get(field, []) or []:
                add(x, "SPECIFICATION", 55, False, f"candidate_facts.{field}")

        for field, typ, priority in (
            ("important_context", "CONTEXT", 50),
            ("usage_scenarios", "CONTEXT", 45),
            ("design_features", "FEATURE", 42),
            ("functional_features", "FEATURE", 42),
            ("search_primary_keywords", "SEARCH_TERM", 38),
            ("search_secondary_keywords", "SEARCH_TERM", 30),
            ("source_title_segments", "SOURCE_CONTEXT", 35),
        ):
            for x in cf.get(field, []) or []:
                add(x, typ, priority, False, f"candidate_facts.{field}", True)

        return {
            "version": TitleFactResolver.VERSION,
            "approved_facts": approved,
            "rejected_facts": rejected,
            "source_available": bool(source),
        }
