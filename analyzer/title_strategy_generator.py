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

            return result

        except Exception as exc:
            raise TitleStrategyError(
                f"Title strategy parse failed: {exc}"
            )

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
            # 其他 required 候选
            #
            # 例如：
            # compatibility
            # model
            # part number
            # 关键规格
            # =========================================

            elif required:

                group = 1


            # =========================================
            # Group 2
            #
            # 可选候选
            # =========================================

            else:

                group = 2


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
            "schema_version"
        ] = "2.8-title-strategy-incremental-value"

        return result
