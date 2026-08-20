from __future__ import annotations

import json

from openai import OpenAI

from services.ai_runtime import DEFAULT_TIMEOUT_SECONDS, execute_with_retry

from .title_strategy_prompt import (
    TITLE_STRATEGY_SYSTEM_PROMPT,
)


class TitleStrategyError(Exception):
    pass


class TitleStrategyGenerator:

    @staticmethod
    def generate(
        profile: dict,
        api_key: str,
        model="gpt-4.1-mini",
    ):

        client = OpenAI(
            api_key=api_key,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            max_retries=0,
        )

        # =================================================
        # Title Strategy Input
        #
        # Title Strategy 只读取已经标准化后的统一输入。
        #
        # 不再直接读取：
        # - product_identity
        # - product_knowledge
        # - compatibility
        # - fact_lock
        # - basic_info
        #
        # 避免多个事实来源重新产生歧义。
        # =================================================

        strategy_input = profile.get(
            "title_strategy_input",
            {},
        )

        if not isinstance(
            strategy_input,
            dict,
        ):
            raise TitleStrategyError(
                "title_strategy_input must be a dictionary"
            )

        if not strategy_input:
            raise TitleStrategyError(
                "title_strategy_input is missing"
            )

        locked = strategy_input.get(
            "locked",
            {},
        )

        if not isinstance(
            locked,
            dict,
        ):
            raise TitleStrategyError(
                "title_strategy_input.locked must be a dictionary"
            )

        locked_identity = locked.get(
            "identity",
            {},
        )

        if not isinstance(
            locked_identity,
            dict,
        ):
            raise TitleStrategyError(
                "title_strategy_input.locked.identity must be a dictionary"
            )

        locked_identity_text = str(
            locked_identity.get(
                "text",
                "",
            )
            or
            ""
        ).strip()

        if not locked_identity_text:
            raise TitleStrategyError(
                "title_strategy_input.locked.identity.text is missing"
            )

        # =================================================
        # Strategy Payload
        #
        # 不直接修改 profile["title_strategy_input"]。
        # 创建发送给 AI 的独立副本，并添加标题策略约束。
        # =================================================

        strategy_payload = dict(
            strategy_input
        )

        strategy_payload[
            "title_constraints"
        ] = {
            "marketplace":
                "Amazon",

            "max_title_length":
                75,

            "objective":
                "maximize purchase-relevant information within the title limit",
        }

        def _request_once():
            return client.chat.completions.create(
                model=model,

            messages=[
                {
                    "role":
                        "system",

                    "content":
                        TITLE_STRATEGY_SYSTEM_PROMPT,
                },

                {
                    "role":
                        "user",

                    "content":
                        json.dumps(
                            strategy_payload,
                            ensure_ascii=False,
                            indent=2,
                        ),
                },
            ],

            response_format={
                "type":
                    "json_object"
            },
            )

        response = execute_with_retry(
            _request_once,
            stage="title_strategy",
        )

        try:
            result = json.loads(
                response.choices[0]
                .message
                .content
            )

            result = (
                TitleStrategyGenerator
                .normalize_strategy_result(
                    result
                )
            )

            # =============================================
            # V3.2 Core Budget Validator + Targeted Repair
            #
            # Normal products do NOT make another AI call.
            # Only unresolved protected-core cases enter this path.
            # =============================================

            result = (
                TitleStrategyGenerator
                .repair_core_overflow_if_needed(
                    result=result,
                    client=client,
                    model=model,
                )
            )

            return result

        except Exception as exc:
            raise TitleStrategyError(
                f"Title strategy parse failed: {exc}"
            )


    @staticmethod
    def _candidate_shortest_text(
        candidate: dict,
    ) -> str:

        if not isinstance(
            candidate,
            dict,
        ):
            return ""

        full_text = str(
            candidate.get(
                "text",
                "",
            )
            or
            ""
        ).strip()

        short_text = str(
            candidate.get(
                "short_text",
                "",
            )
            or
            ""
        ).strip()

        if (
            short_text
            and
            len(short_text)
            <
            len(full_text)
        ):
            return short_text

        return full_text


    @staticmethod
    def _current_protected_candidates(
        result: dict,
    ) -> list:

        candidates = result.get(
            "title_candidates",
            [],
        )

        if not isinstance(
            candidates,
            list,
        ):
            return []

        protected = []

        for candidate in candidates:

            if not isinstance(
                candidate,
                dict,
            ):
                continue

            if not bool(
                candidate.get(
                    "required",
                    False,
                )
            ):
                continue

            candidate_type = str(
                candidate.get(
                    "type",
                    "",
                )
                or
                ""
            ).upper()

            # Single-unit quantity is not a protected title prefix.
            if candidate_type == "QUANTITY":

                quantity_text = str(
                    candidate.get(
                        "text",
                        "",
                    )
                    or
                    ""
                ).strip()

                match = __import__(
                    "re"
                ).match(
                    r"^\\s*(\\d+)\\b",
                    quantity_text,
                )

                if match:

                    try:
                        if int(
                            match.group(1)
                        ) <= 1:
                            continue
                    except Exception:
                        pass

            protected.append(
                candidate
            )

        return protected


    @staticmethod
    def _protected_bundle_length(
        result: dict,
    ) -> int:

        parts = [
            TitleStrategyGenerator
            ._candidate_shortest_text(
                candidate
            )
            for candidate
            in TitleStrategyGenerator
            ._current_protected_candidates(
                result
            )
        ]

        parts = [
            part
            for part in parts
            if part
        ]

        return len(
            " ".join(
                parts
            )
        )


    @staticmethod
    def _identity_short_is_structurally_safe(
        full_text: str,
        short_text: str,
    ) -> bool:
        """
        Conservative deterministic guard.

        The repair model may REMOVE words from the locked identity,
        but it may not invent a different product expression here.

        This is intentionally strict:
        - short must actually be shorter
        - at least 2 tokens for multi-word identities
        - every significant short token must already exist in full identity
        - final head token should be preserved
        """

        full_text = str(
            full_text
            or
            ""
        ).strip()

        short_text = str(
            short_text
            or
            ""
        ).strip()

        if not full_text or not short_text:
            return False

        if len(short_text) >= len(full_text):
            return False

        token_pattern = __import__(
            "re"
        ).compile(
            r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*"
        )

        full_tokens = [
            token.casefold()
            for token in token_pattern.findall(
                full_text
            )
        ]

        short_tokens = [
            token.casefold()
            for token in token_pattern.findall(
                short_text
            )
        ]

        if not short_tokens:
            return False

        if (
            len(full_tokens) > 1
            and
            len(short_tokens) < 2
        ):
            return False

        full_token_set = set(
            full_tokens
        )

        if any(
            token
            not in full_token_set
            for token in short_tokens
        ):
            return False

        # Preserve the final product-head token when possible.
        if (
            full_tokens
            and
            short_tokens
            and
            full_tokens[-1]
            !=
            short_tokens[-1]
        ):
            return False

        return True


    @staticmethod
    def _compatibility_short_is_structurally_safe(
        full_text: str,
        short_text: str,
    ) -> bool:
        """
        Compatibility repair may shorten a long compatible-brand list,
        but it may never invent a brand and must keep the explicit
        'Compatible with' qualifier.
        """

        full_text = str(
            full_text
            or
            ""
        ).strip()

        short_text = str(
            short_text
            or
            ""
        ).strip()

        if not full_text or not short_text:
            return False

        if len(short_text) >= len(full_text):
            return False

        required_prefix = "compatible with "

        if not short_text.casefold().startswith(
            required_prefix
        ):
            return False

        short_body = short_text[
            len(
                "Compatible with "
            ):
        ].strip()

        if not short_body:
            return False

        # Split common multi-brand separators and verify every retained
        # brand/model fragment came from the original compatibility phrase.
        fragments = [
            fragment.strip()
            for fragment in __import__(
                "re"
            ).split(
                r"[,;/|]+",
                short_body,
            )
            if fragment.strip()
        ]

        full_fold = full_text.casefold()

        if not fragments:
            return False

        return all(
            fragment.casefold()
            in full_fold
            for fragment in fragments
        )


    @staticmethod
    def _classify_core_overflow(
        result: dict,
    ) -> str:

        protected = (
            TitleStrategyGenerator
            ._current_protected_candidates(
                result
            )
        )

        if not protected:
            return "none"

        identity = next(
            (
                candidate
                for candidate in protected
                if str(
                    candidate.get(
                        "type",
                        "",
                    )
                    or
                    ""
                ).upper()
                ==
                "IDENTITY"
            ),
            None,
        )

        compatibility = next(
            (
                candidate
                for candidate in protected
                if str(
                    candidate.get(
                        "type",
                        "",
                    )
                    or
                    ""
                ).upper()
                ==
                "COMPATIBILITY"
            ),
            None,
        )

        models = [
            candidate
            for candidate in protected
            if str(
                candidate.get(
                    "type",
                    "",
                )
                or
                ""
            ).upper()
            in {
                "MODEL",
                "PART_NUMBER",
            }
        ]

        total = (
            TitleStrategyGenerator
            ._protected_bundle_length(
                result
            )
        )

        if total <= 75:
            return "none"

        identity_text = (
            TitleStrategyGenerator
            ._candidate_shortest_text(
                identity
            )
            if identity
            else
            ""
        )

        compatibility_text = (
            TitleStrategyGenerator
            ._candidate_shortest_text(
                compatibility
            )
            if compatibility
            else
            ""
        )

        identity_compatibility_length = len(
            " ".join(
                part
                for part in [
                    identity_text,
                    compatibility_text,
                ]
                if part
            )
        )

        if (
            compatibility_text
            and
            len(compatibility_text)
            >= 45
        ):
            return "compatibility_overflow"

        if (
            identity_text
            and
            len(identity_text)
            >= 30
        ):
            return "identity_overflow"

        if len(models) > 1:
            return "model_overflow"

        if identity_compatibility_length > 75:
            return "identity_compatibility_overflow"

        return "mixed_core_overflow"


    @staticmethod
    def repair_core_overflow_if_needed(
        result: dict,
        client,
        model: str,
    ) -> dict:
        """
        V3.3 Exact Character Budget + Two-Pass Targeted Repair.

        Root-cause behavior:
        - normal products make NO extra AI request
        - overflow products receive an exact numeric character target
        - pass 1 attempts a safe targeted repair
        - if still >75, pass 2 recalculates the remaining shortage and
          gives AI a tighter exact budget
        - at most 2 repair calls
        - quantity / model / part number are never rewritten here
        """

        if not isinstance(result, dict):
            return result

        required_budget = result.get("required_budget", {})
        if not isinstance(required_budget, dict):
            required_budget = {}
            result["required_budget"] = required_budget

        def _protected():
            return (
                TitleStrategyGenerator
                ._current_protected_candidates(result)
            )

        def _bundle_length():
            return (
                TitleStrategyGenerator
                ._protected_bundle_length(result)
            )

        def _candidate_of_type(type_name: str):
            for candidate in result.get("title_candidates", []):
                if (
                    isinstance(candidate, dict)
                    and bool(candidate.get("required", False))
                    and str(candidate.get("type", "") or "").upper()
                    == type_name
                ):
                    return candidate
            return None

        def _models():
            return [
                candidate
                for candidate in result.get("title_candidates", [])
                if (
                    isinstance(candidate, dict)
                    and bool(candidate.get("required", False))
                    and str(candidate.get("type", "") or "").upper()
                    in {"MODEL", "PART_NUMBER"}
                )
            ]

        def _quantities():
            return [
                candidate
                for candidate in result.get("title_candidates", [])
                if (
                    isinstance(candidate, dict)
                    and bool(candidate.get("required", False))
                    and str(candidate.get("type", "") or "").upper()
                    == "QUANTITY"
                )
            ]

        def _max_chars_for(candidate_to_replace: dict | None) -> int:
            """
            Exact maximum characters available to one protected candidate
            if every other protected item remains at its current shortest
            safe representation.
            """
            if not isinstance(candidate_to_replace, dict):
                return 0

            other_parts = []

            for candidate in _protected():
                if candidate is candidate_to_replace:
                    continue

                part = (
                    TitleStrategyGenerator
                    ._candidate_shortest_text(candidate)
                )

                if part:
                    other_parts.append(part)

            if not other_parts:
                return 75

            # One separating space will be needed between the replacement
            # candidate and the already-protected remainder.
            return max(
                0,
                75
                -
                len(" ".join(other_parts))
                -
                1,
            )

        def _refresh_diagnostics():
            current = _bundle_length()

            required_budget[
                "protected_bundle_length"
            ] = current

            required_budget[
                "resolved"
            ] = current <= 75

            required_budget[
                "overflow_type"
            ] = (
                TitleStrategyGenerator
                ._classify_core_overflow(result)
            )

            required_budget[
                "characters_over_budget"
            ] = max(0, current - 75)

            return current

        current_length = _refresh_diagnostics()

        required_budget.setdefault(
            "repair_attempted",
            False,
        )
        required_budget.setdefault(
            "repair_applied",
            False,
        )
        required_budget.setdefault(
            "repair_type",
            "",
        )
        required_budget.setdefault(
            "repair_reason",
            "",
        )
        required_budget[
            "repair_passes"
        ] = 0
        required_budget[
            "repair_history"
        ] = []

        # Fast path — normal products never pay for another AI call.
        if current_length <= 75:
            return result

        identity = _candidate_of_type("IDENTITY")
        compatibility = _candidate_of_type("COMPATIBILITY")

        original_identity_short = (
            str(identity.get("short_text", "") or "").strip()
            if identity
            else ""
        )
        original_compatibility_short = (
            str(compatibility.get("short_text", "") or "").strip()
            if compatibility
            else ""
        )

        any_safe_change = False
        applied_identity = False
        applied_compatibility = False
        last_reason = ""

        for repair_pass in (1, 2):

            current_length = _refresh_diagnostics()

            if current_length <= 75:
                break

            identity_max_chars = (
                _max_chars_for(identity)
                if identity
                else 0
            )

            compatibility_max_chars = (
                _max_chars_for(compatibility)
                if compatibility
                else 0
            )

            identity_current = (
                TitleStrategyGenerator
                ._candidate_shortest_text(identity)
                if identity
                else ""
            )

            compatibility_current = (
                TitleStrategyGenerator
                ._candidate_shortest_text(compatibility)
                if compatibility
                else ""
            )

            repair_payload = {
                "max_title_length":
                    75,

                "repair_pass":
                    repair_pass,

                "overflow_type":
                    required_budget.get(
                        "overflow_type",
                        "",
                    ),

                "current_protected_bundle_length":
                    current_length,

                "characters_that_must_be_removed":
                    max(
                        0,
                        current_length - 75,
                    ),

                "identity":
                    {
                        "full_text":
                            (
                                str(
                                    identity.get(
                                        "text",
                                        "",
                                    )
                                    or
                                    ""
                                ).strip()
                                if identity
                                else
                                ""
                            ),
                        "current_effective_text":
                            identity_current,
                        "maximum_allowed_characters":
                            identity_max_chars,
                    },

                "compatibility":
                    {
                        "full_text":
                            (
                                str(
                                    compatibility.get(
                                        "text",
                                        "",
                                    )
                                    or
                                    ""
                                ).strip()
                                if compatibility
                                else
                                ""
                            ),
                        "current_effective_text":
                            compatibility_current,
                        "maximum_allowed_characters":
                            compatibility_max_chars,
                    },

                "protected_models_and_part_numbers":
                    [
                        str(
                            candidate.get(
                                "text",
                                "",
                            )
                            or
                            ""
                        ).strip()
                        for candidate in _models()
                    ],

                "protected_quantity":
                    [
                        str(
                            candidate.get(
                                "text",
                                "",
                            )
                            or
                            ""
                        ).strip()
                        for candidate in _quantities()
                    ],
            }

            repair_prompt = """
You are repairing ONLY an Amazon title protected-core overflow.

Do not write a complete title.
Do not reinterpret the product.
Do not invent facts.

HARD REQUIREMENT:
The protected bundle must fit within 75 characters including spaces.

The user payload gives:
- current_protected_bundle_length
- characters_that_must_be_removed
- maximum_allowed_characters for IDENTITY
- maximum_allowed_characters for COMPATIBILITY

These are REAL character limits, not suggestions.

You may ONLY do the following:

1. IDENTITY compression
   - Preserve the same physical product type.
   - Remove only redundant generic context, duplicated nouns,
     overlapping descriptors, or non-essential modifiers.
   - Never replace the identity with a broader category.
   - Never remove the product-defining head noun.
   - Prefer words already present in the full identity.
   - If you return identity_short_text, its character count MUST be
     <= identity.maximum_allowed_characters.

2. COMPATIBILITY compression
   - Keep the exact prefix "Compatible with".
   - If a long multi-brand phrase causes overflow, retain only the
     highest-value brand(s) needed in the title.
   - Every retained brand must already occur in the original phrase.
   - Never invent compatibility.
   - If you return compatibility_short_text, its character count MUST be
     <= compatibility.maximum_allowed_characters.

Never change:
- quantity
- model numbers
- part numbers

IMPORTANT:
A proposal that is shorter but still leaves the protected bundle above
75 characters is NOT a successful repair.

Return JSON only:

{
  "safe": true,
  "identity_short_text": "",
  "compatibility_short_text": "",
  "repair_type": "identity|compatibility|identity_and_compatibility|none",
  "reason": ""
}

If no semantically safe expression can satisfy the supplied numeric
budget, return safe=false and repair_type="none".
"""

            def _repair_once():
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role":
                                "system",
                            "content":
                                repair_prompt,
                        },
                        {
                            "role":
                                "user",
                            "content":
                                json.dumps(
                                    repair_payload,
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                        },
                    ],
                    response_format={
                        "type":
                            "json_object"
                    },
                )

            required_budget[
                "repair_attempted"
            ] = True
            required_budget[
                "repair_passes"
            ] = repair_pass

            try:
                repair_response = execute_with_retry(
                    _repair_once,
                    stage=(
                        "title_strategy_core_repair_"
                        f"pass_{repair_pass}"
                    ),
                )

                repair_result = json.loads(
                    repair_response
                    .choices[0]
                    .message
                    .content
                )

            except Exception as exc:
                last_reason = (
                    f"repair_pass_{repair_pass}_call_failed: {exc}"
                )

                required_budget[
                    "repair_history"
                ].append(
                    {
                        "pass":
                            repair_pass,
                        "before_length":
                            current_length,
                        "applied":
                            False,
                        "reason":
                            last_reason,
                    }
                )
                continue

            if not isinstance(repair_result, dict):
                last_reason = (
                    f"repair_pass_{repair_pass}_result_not_dict"
                )

                required_budget[
                    "repair_history"
                ].append(
                    {
                        "pass":
                            repair_pass,
                        "before_length":
                            current_length,
                        "applied":
                            False,
                        "reason":
                            last_reason,
                    }
                )
                continue

            if not bool(repair_result.get("safe", False)):
                last_reason = str(
                    repair_result.get(
                        "reason",
                        f"repair_pass_{repair_pass}_no_safe_repair",
                    )
                    or
                    f"repair_pass_{repair_pass}_no_safe_repair"
                )

                required_budget[
                    "repair_history"
                ].append(
                    {
                        "pass":
                            repair_pass,
                        "before_length":
                            current_length,
                        "applied":
                            False,
                        "reason":
                            last_reason,
                    }
                )
                continue

            identity_short = str(
                repair_result.get(
                    "identity_short_text",
                    "",
                )
                or
                ""
            ).strip()

            compatibility_short = str(
                repair_result.get(
                    "compatibility_short_text",
                    "",
                )
                or
                ""
            ).strip()

            pass_identity_applied = False
            pass_compatibility_applied = False

            if (
                identity
                and
                identity_short
                and
                len(identity_short) <= identity_max_chars
                and
                TitleStrategyGenerator
                ._identity_short_is_structurally_safe(
                    str(
                        identity.get(
                            "text",
                            "",
                        )
                        or
                        ""
                    ),
                    identity_short,
                )
            ):
                identity[
                    "short_text"
                ] = identity_short
                pass_identity_applied = True
                applied_identity = True
                any_safe_change = True

            if (
                compatibility
                and
                compatibility_short
                and
                len(compatibility_short)
                <= compatibility_max_chars
                and
                TitleStrategyGenerator
                ._compatibility_short_is_structurally_safe(
                    str(
                        compatibility.get(
                            "text",
                            "",
                        )
                        or
                        ""
                    ),
                    compatibility_short,
                )
            ):
                compatibility[
                    "short_text"
                ] = compatibility_short
                pass_compatibility_applied = True
                applied_compatibility = True
                any_safe_change = True

            after_length = _refresh_diagnostics()

            required_budget[
                "repair_history"
            ].append(
                {
                    "pass":
                        repair_pass,
                    "before_length":
                        current_length,
                    "after_length":
                        after_length,
                    "characters_removed":
                        max(
                            0,
                            current_length - after_length,
                        ),
                    "identity_max_chars":
                        identity_max_chars,
                    "compatibility_max_chars":
                        compatibility_max_chars,
                    "identity_applied":
                        pass_identity_applied,
                    "compatibility_applied":
                        pass_compatibility_applied,
                    "applied":
                        (
                            pass_identity_applied
                            or
                            pass_compatibility_applied
                        ),
                    "reason":
                        str(
                            repair_result.get(
                                "reason",
                                "",
                            )
                            or
                            ""
                        ),
                }
            )

            last_reason = str(
                repair_result.get(
                    "reason",
                    "",
                )
                or
                ""
            )

            if after_length <= 75:
                break

        final_length = _refresh_diagnostics()

        if final_length <= 75:
            required_budget[
                "repair_applied"
            ] = any_safe_change

            if applied_identity and applied_compatibility:
                required_budget[
                    "repair_type"
                ] = "identity_and_compatibility"
            elif applied_identity:
                required_budget[
                    "repair_type"
                ] = "identity"
            elif applied_compatibility:
                required_budget[
                    "repair_type"
                ] = "compatibility"
            else:
                required_budget[
                    "repair_type"
                ] = ""

            required_budget[
                "repair_reason"
            ] = (
                last_reason
                or
                "protected_core_resolved"
            )

            return result

        # If the two-pass process could not fully resolve the protected core,
        # restore original short forms. This keeps failed repair attempts from
        # silently changing product semantics or title behavior.
        if identity:
            identity[
                "short_text"
            ] = original_identity_short

        if compatibility:
            compatibility[
                "short_text"
            ] = original_compatibility_short

        final_length = _refresh_diagnostics()

        required_budget[
            "repair_applied"
        ] = False

        required_budget[
            "repair_type"
        ] = ""

        required_budget[
            "repair_reason"
        ] = (
            last_reason
            or
            "two_pass_repair_did_not_resolve_75_char_budget"
        )

        return result


    @staticmethod
    def normalize_strategy_result(
        result: dict,
    ) -> dict:
        """
        对 Title Strategy AI 输出做结构标准化。

        注意：

        这里只做 Schema 保护。

        不重新判断：
        - 什么信息重要
        - 什么是型号
        - 什么是规格
        - 什么应该进入标题

        这些判断必须由 AI Strategy 完成。
        """

        if not isinstance(
            result,
            dict,
        ):
            raise TitleStrategyError(
                "Title strategy result must be a dictionary"
            )

        # =============================================
        # Legacy Fields
        # =============================================

        legacy_list_fields = [
            "must_include",
            "optional_include",
            "exclude",
            "model_priority",
            "compatibility_priority",
            "title_structure",
            "priority_order",
        ]

        for field in legacy_list_fields:
            value = result.get(
                field,
                []
            )

            if not isinstance(
                value,
                list,
            ):
                value = []

            cleaned = []

            for item in value:
                text = str(
                    item
                ).strip()

                if not text:
                    continue

                if text not in cleaned:
                    cleaned.append(
                        text
                    )

            result[
                field
            ] = cleaned

        legacy_text_fields = [
            "core_product",
            "buyer_search_intent",
            "title_length_strategy",
            "reasoning",
        ]

        for field in legacy_text_fields:
            value = result.get(
                field,
                ""
            )

            if value is None:
                value = ""

            result[
                field
            ] = str(
                value
            ).strip()

        # =============================================
        # Title Candidates
        # =============================================

        candidates = result.get(
            "title_candidates",
            []
        )

        if not isinstance(
            candidates,
            list,
        ):
            candidates = []

        allowed_types = {
            "IDENTITY",
            "SECONDARY_IDENTITY",
            "MODEL",
            "PART_NUMBER",
            "COMPATIBILITY",
            "FEATURE",
            "SPECIFICATION",
            "QUANTITY",
            "MATERIAL",
            "USAGE",
            "SEARCH_TERM",
            "OTHER",
        }

        allowed_priorities = {
            "S",
            "A",
            "B",
            "C",
            "D",
        }

        normalized_candidates = []
        seen = set()

        for candidate in candidates:

            if not isinstance(
                candidate,
                dict,
            ):
                continue

            text = str(
                candidate.get(
                    "text",
                    ""
                )
            ).strip()

            if not text:
                continue

            short_text = str(
                candidate.get(
                    "short_text",
                    ""
                )
                or
                ""
            ).strip()

            candidate_type = str(
                candidate.get(
                    "type",
                    "OTHER"
                )
            ).strip().upper()

            if (
                candidate_type
                not in allowed_types
            ):
                candidate_type = "OTHER"

            priority = str(
                candidate.get(
                    "priority",
                    "C"
                )
            ).strip().upper()

            if (
                priority
                not in allowed_priorities
            ):
                priority = "C"

            raw_scores = candidate.get(
                "scores",
                {}
            )

            if not isinstance(
                raw_scores,
                dict,
            ):
                raw_scores = {}

            def normalize_score(
                value,
            ) -> int:
                """
                Score Schema保护。

                这里只负责：
                - 转数字
                - 限制0~100

                不重新判断产品价值。
                """

                try:
                    score_value = float(
                        value
                    )

                except (
                    TypeError,
                    ValueError,
                ):
                    score_value = 0.0

                score_value = max(
                    0.0,
                    min(
                        100.0,
                        score_value,
                    ),
                )

                return int(
                    round(
                        score_value
                    )
                )

            scores = {
                "search_value":
                    normalize_score(
                        raw_scores.get(
                            "search_value",
                            0,
                        )
                    ),

                "purchase_impact":
                    normalize_score(
                        raw_scores.get(
                            "purchase_impact",
                            0,
                        )
                    ),

                "identity_value":
                    normalize_score(
                        raw_scores.get(
                            "identity_value",
                            0,
                        )
                    ),

                "differentiation_value":
                    normalize_score(
                        raw_scores.get(
                            "differentiation_value",
                            0,
                        )
                    ),

                "character_efficiency":
                    normalize_score(
                        raw_scores.get(
                            "character_efficiency",
                            0,
                        )
                    ),
            }

            final_score = round(
                (
                    scores[
                        "search_value"
                    ]
                    * 0.30
                )
                +
                (
                    scores[
                        "purchase_impact"
                    ]
                    * 0.25
                )
                +
                (
                    scores[
                        "identity_value"
                    ]
                    * 0.20
                )
                +
                (
                    scores[
                        "differentiation_value"
                    ]
                    * 0.15
                )
                +
                (
                    scores[
                        "character_efficiency"
                    ]
                    * 0.10
                ),
                1,
            )

            raw_incremental = candidate.get(
                "incremental_value",
                None,
            )

            has_incremental = isinstance(
                raw_incremental,
                dict,
            )

            if not has_incremental:
                raw_incremental = {}

            incremental_value = {
                "new_information":
                    normalize_score(
                        raw_incremental.get(
                            "new_information",
                            0,
                        )
                    ),

                "redundancy_penalty":
                    normalize_score(
                        raw_incremental.get(
                            "redundancy_penalty",
                            0,
                        )
                    ),

                "selection_value":
                    normalize_score(
                        raw_incremental.get(
                            "selection_value",
                            0,
                        )
                    ),
            }

            if has_incremental:

                incremental_modifier = (
                    incremental_value[
                        "new_information"
                    ]
                    * 0.50
                    +
                    incremental_value[
                        "selection_value"
                    ]
                    * 0.30
                    +
                    (
                        100
                        -
                        incremental_value[
                            "redundancy_penalty"
                        ]
                    )
                    * 0.20
                )

                adjusted_score = round(
                    final_score
                    *
                    (
                        0.50
                        +
                        (
                            incremental_modifier
                            / 200.0
                        )
                    ),
                    1,
                )

            else:
                incremental_modifier = 100.0
                adjusted_score = final_score

            required = candidate.get(
                "required",
                False
            )

            if not isinstance(
                required,
                bool,
            ):
                required = False

            reason = str(
                candidate.get(
                    "reason",
                    ""
                )
                or
                ""
            ).strip()

            duplicate_key = (
                text.casefold()
            )

            if duplicate_key in seen:
                continue

            seen.add(
                duplicate_key
            )

            normalized_candidates.append(
                {
                    "text":
                        text,

                    "short_text":
                        short_text,

                    "type":
                        candidate_type,

                    "priority":
                        priority,

                    "scores":
                        scores,

                    "final_score":
                        final_score,

                    "incremental_value":
                        incremental_value,

                    "incremental_modifier":
                        round(
                            incremental_modifier,
                            1,
                        ),

                    "adjusted_score":
                        adjusted_score,

                    "required":
                        required,

                    "reason":
                        reason,
                }
            )
        # =============================================
        # V3.0 Required Budget Arbitration
        #
        # Root cause:
        # The AI may mark too many FEATURE / SPECIFICATION / MATERIAL /
        # COLOR candidates as required. If every "required" flag is treated
        # as untouchable, the protected bundle itself can exceed 75 chars.
        #
        # Rule:
        # 1. Never demote IDENTITY.
        # 2. Never demote COMPATIBILITY.
        # 3. Never demote multi-unit QUANTITY.
        # 4. Protect up to the two strongest required MODEL/PART_NUMBER
        #    candidates.
        # 5. Other AI-required candidates remain required only while the
        #    shortest safe protected bundle fits within 75 characters.
        # 6. When the bundle is too long, demote the lowest marginal-value
        #    non-core required candidate to optional and repeat.
        #
        # This is NOT semantic rewriting. It only resolves conflicts between
        # AI "required" flags under the fixed 75-character title budget.
        # =============================================

        def candidate_shortest_text(
            candidate,
        ):

            full_text = str(
                candidate.get(
                    "text",
                    ""
                )
                or
                ""
            ).strip()

            short_text = str(
                candidate.get(
                    "short_text",
                    ""
                )
                or
                ""
            ).strip()

            if (
                short_text
                and
                len(short_text)
                <
                len(full_text)
            ):
                return short_text

            return full_text


        def bundle_length(
            bundle,
        ):

            parts = [
                candidate_shortest_text(
                    candidate
                )
                for candidate in bundle
            ]

            parts = [
                part
                for part in parts
                if part
            ]

            return len(
                " ".join(
                    parts
                )
            )


        def parse_quantity_count(
            candidate,
        ):
            """
            Extract a leading package count from a QUANTITY candidate.

            Examples:
            "10 PCS" -> 10
            "5 pcs" -> 5
            "1 Piece" -> 1

            Returns None when no trustworthy leading integer exists.
            """

            if not isinstance(
                candidate,
                dict,
            ):
                return None

            if str(
                candidate.get(
                    "type",
                    "",
                )
                or
                ""
            ).upper() != "QUANTITY":
                return None

            quantity_text = str(
                candidate.get(
                    "text",
                    "",
                )
                or
                ""
            ).strip()

            match = __import__(
                "re"
            ).match(
                r"^\\s*(\\d+)\\b",
                quantity_text,
            )

            if not match:
                return None

            try:
                return int(
                    match.group(1)
                )
            except Exception:
                return None


        # Preserve the AI decision for diagnostics.
        for candidate in normalized_candidates:

            candidate[
                "required_by_ai"
            ] = bool(
                candidate.get(
                    "required",
                    False
                )
            )

            candidate[
                "required_budget_demoted"
            ] = False


        # Single-unit quantity does not belong in the title prefix and
        # therefore must not consume protected-core budget.
        for candidate in normalized_candidates:

            if str(
                candidate.get(
                    "type",
                    "",
                )
                or
                ""
            ).upper() != "QUANTITY":
                continue

            quantity_count = parse_quantity_count(
                candidate
            )

            if quantity_count == 1:

                candidate[
                    "required"
                ] = False

                candidate[
                    "required_budget_demoted"
                ] = True

                candidate[
                    "required_budget_reason"
                ] = (
                    "single_unit_quantity_not_title_prefix"
                )


        fixed_required = []
        model_required = []
        flexible_required = []

        for candidate in normalized_candidates:

            if not candidate.get(
                "required",
                False
            ):
                continue

            candidate_type = str(
                candidate.get(
                    "type",
                    ""
                )
                or
                ""
            ).upper()

            if candidate_type in {
                "IDENTITY",
                "COMPATIBILITY",
                "QUANTITY",
            }:
                fixed_required.append(
                    candidate
                )
                continue

            if candidate_type in {
                "MODEL",
                "PART_NUMBER",
            }:
                model_required.append(
                    candidate
                )
                continue

            flexible_required.append(
                candidate
            )


        def required_value_key(
            candidate,
        ):

            try:
                adjusted_score = float(
                    candidate.get(
                        "adjusted_score",
                        0
                    )
                    or
                    0
                )
            except (
                TypeError,
                ValueError,
            ):
                adjusted_score = 0.0

            incremental = candidate.get(
                "incremental_value",
                {}
            )

            if not isinstance(
                incremental,
                dict,
            ):
                incremental = {}

            try:
                selection_value = float(
                    incremental.get(
                        "selection_value",
                        0
                    )
                    or
                    0
                )
            except (
                TypeError,
                ValueError,
            ):
                selection_value = 0.0

            try:
                new_information = float(
                    incremental.get(
                        "new_information",
                        0
                    )
                    or
                    0
                )
            except (
                TypeError,
                ValueError,
            ):
                new_information = 0.0

            length_cost = max(
                1,
                len(
                    candidate_shortest_text(
                        candidate
                    )
                )
            )

            # Higher = more valuable per character.
            efficiency = (
                adjusted_score
                * 0.50
                +
                selection_value
                * 0.30
                +
                new_information
                * 0.20
            ) / length_cost

            return (
                efficiency,
                adjusted_score,
                selection_value,
                new_information,
            )


        # Protect at most the two strongest AI-required models/parts.
        model_required.sort(
            key=required_value_key,
            reverse=True,
        )

        protected_model_required = (
            model_required[:2]
        )

        for candidate in model_required[2:]:

            candidate[
                "required"
            ] = False

            candidate[
                "required_budget_demoted"
            ] = True

            candidate[
                "required_budget_reason"
            ] = (
                "more_than_two_primary_model_or_part_candidates"
            )


        active_flexible_required = list(
            flexible_required
        )

        protected_bundle = (
            fixed_required
            +
            protected_model_required
            +
            active_flexible_required
        )


        # If the protected bundle is still too long, a second required
        # MODEL/PART_NUMBER must not displace identity + compatibility +
        # the strongest primary identifier.
        #
        # This implements the established title rule:
        # use one or two high-value models; the second model is conditional
        # on remaining title space.
        while (
            bundle_length(
                protected_bundle
            )
            >
            75
            and
            len(
                protected_model_required
            )
            >
            1
        ):

            candidate_to_demote = (
                protected_model_required.pop()
            )

            candidate_to_demote[
                "required"
            ] = False

            candidate_to_demote[
                "required_budget_demoted"
            ] = True

            candidate_to_demote[
                "required_budget_reason"
            ] = (
                "secondary_required_model_exceeds_core_budget"
            )

            protected_bundle = (
                fixed_required
                +
                protected_model_required
                +
                active_flexible_required
            )


        # Demote lowest marginal-value flexible required candidates until the
        # shortest safe bundle fits. IDENTITY / COMPATIBILITY / QUANTITY and
        # the strongest 1-2 model/part candidates remain protected.
        while (
            bundle_length(
                protected_bundle
            )
            >
            75
            and
            active_flexible_required
        ):

            candidate_to_demote = min(
                active_flexible_required,
                key=required_value_key,
            )

            candidate_to_demote[
                "required"
            ] = False

            candidate_to_demote[
                "required_budget_demoted"
            ] = True

            candidate_to_demote[
                "required_budget_reason"
            ] = (
                "protected_required_bundle_exceeds_75"
            )

            active_flexible_required.remove(
                candidate_to_demote
            )

            protected_bundle = (
                fixed_required
                +
                protected_model_required
                +
                active_flexible_required
            )


        required_budget_summary = {
            "protected_bundle_length":
                bundle_length(
                    protected_bundle
                ),
            "ai_required_count":
                sum(
                    1
                    for candidate
                    in normalized_candidates
                    if candidate.get(
                        "required_by_ai",
                        False
                    )
                ),
            "final_required_count":
                sum(
                    1
                    for candidate
                    in normalized_candidates
                    if candidate.get(
                        "required",
                        False
                    )
                ),
            "demoted_count":
                sum(
                    1
                    for candidate
                    in normalized_candidates
                    if candidate.get(
                        "required_budget_demoted",
                        False
                    )
                ),
            "resolved":
                bundle_length(
                    protected_bundle
                )
                <=
                75,

            "repair_attempted":
                False,

            "repair_applied":
                False,

            "repair_type":
                "",

            "repair_reason":
                "",
        }


        # =============================================
        # Candidate Final Ordering
        #
        # Title Strategy AI 负责：
        # - 语义判断
        # - priority
        # - required
        # - incremental value
        #
        # Normalizer 负责：
        # - final_score
        # - adjusted_score
        # - 将这些确定性结果转化为最终候选顺序
        #
        # TitleGenerator 不再重新排序。
        # =============================================

        priority_rank = {
            "S": 0,
            "A": 1,
            "B": 2,
            "C": 3,
            "D": 4,
        }


        def candidate_sort_key(
            item,
        ):

            candidate_type = str(
                item.get(
                    "type",
                    "OTHER",
                )
                or
                "OTHER"
            ).upper()


            required = item.get(
                "required",
                False,
            )


            if not isinstance(
                required,
                bool,
            ):
                required = False


            try:

                adjusted_score = float(
                    item.get(
                        "adjusted_score",
                        0,
                    )
                    or
                    0
                )

            except (
                TypeError,
                ValueError,
            ):

                adjusted_score = 0.0


            priority = str(
                item.get(
                    "priority",
                    "D",
                )
                or
                "D"
            ).upper()


            # =========================================
            # Group 0
            #
            # Primary required identity
            #
            # 必须永远位于标题最前面。
            # =========================================

            if (
                candidate_type
                ==
                "IDENTITY"
                and
                required
            ):

                group = 0


            # =========================================
            # Group 1
            #
            # Compatibility brand is protected ahead
            # of optional secondary identity/context.
            # =========================================

            elif candidate_type == "COMPATIBILITY":

                group = 1


            # =========================================
            # Group 2
            #
            # AI-selected primary model / part number.
            # Strategy marks only the strongest 1-2 as
            # required when their selection value is high.
            # =========================================

            elif (
                candidate_type
                in {
                    "MODEL",
                    "PART_NUMBER",
                }
                and
                required
            ):

                group = 2


            # =========================================
            # Group 3
            #
            # Other high-value supporting information.
            #
            # SECONDARY_IDENTITY is deliberately NOT
            # protected. It competes here by adjusted
            # incremental value and character efficiency.
            # This prevents a long/redundant secondary
            # identity from displacing compatibility or
            # primary models.
            # =========================================

            elif candidate_type not in {
                "MODEL",
                "PART_NUMBER",
                "SEARCH_TERM",
            }:

                group = 3


            # =========================================
            # Group 4
            #
            # Completion models / part numbers.
            # Used after stronger supporting facts.
            # =========================================

            elif candidate_type in {
                "MODEL",
                "PART_NUMBER",
            }:

                group = 4


            # =========================================
            # Group 5
            #
            # Remaining search/context completion.
            # =========================================

            else:

                group = 5


            return (
                group,

                # adjusted_score 是组内核心排序依据
                -adjusted_score,

                # priority 只作为辅助排序
                priority_rank.get(
                    priority,
                    99,
                ),
            )


        normalized_candidates.sort(
            key=candidate_sort_key
        )
        result[
            "title_candidates"
        ] = normalized_candidates

        # =============================================
        # Schema Version
        # =============================================

        result[
            "required_budget"
        ] = required_budget_summary

        result[
            "schema_version"
        ] = "3.3-exact-budget-two-pass-repair"

        return result
