from __future__ import annotations

import re

from generator.candidate_budget import CandidateBudgetEngine


class TitleGenerator:


    BLOCKED_WORDS = [
        "best",
        "best seller",
        "#1",
        "premium",
        "original",
        "genuine",
        "official",
        "authentic",
        "hot sale",
        "discount",
        "promotion",
        "oem",
    ]


    IGNORED_ATTRIBUTES = [
        "PP",
        "ABS",
        "plastic",
        "metal",
        "stainless steel",
    ]
    @staticmethod
    def add_budget_part(
        title_parts,
        text,
        max_length=75,
        required=False,
    ):
        """
        将一个候选标题元素加入 title_parts。

        统一负责：

        1. 空值过滤
        2. 完全重复过滤
        3. 语义包含重复过滤
        4. 75字符预算检查
        5. required 信息保护

        返回：
            True  -> 已加入
            False -> 未加入
        """

        if text is None:
            return False


        text = str(
            text
        ).strip()


        if not text:
            return False


        # ==========================================
        # 1. 完全重复检查
        # ==========================================

        for existing in title_parts:

            if (
                str(existing)
                .strip()
                .lower()
                ==
                text.lower()
            ):

                return False


        # ==========================================
        # 2. 语义包含检查
        #
        # 例如：
        #
        # 已有：
        # 9D Floating Head Shaver
        #
        # 新：
        # 9D Floating Head
        #
        # 不再重复加入。
        # ==========================================

        if TitleGenerator.is_contained_information(
            text,
            title_parts,
        ):

            return False


        # ==========================================
        # 3. 计算加入后的标题长度
        # ==========================================

        candidate_parts = (
            list(title_parts)
            +
            [text]
        )


        candidate_title = " ".join(
            str(item).strip()
            for item in candidate_parts
            if str(item).strip()
        )


        # ==========================================
        # 4. 预算检查
        # ==========================================

        if len(candidate_title) <= max_length:

            title_parts.append(
                text
            )

            return True


        # ==========================================
        # 5. Required
        #
        # required=True 不代表强行超过75字符。
        #
        # 它表示：
        # 这是高价值信息，但当前剩余预算不足。
        #
        # 先返回False。
        # 后续V2第二阶段会加入：
        # lower priority replacement。
        # ==========================================

        if required:

            return False


        return False
    @staticmethod
    def is_contained_information(
        new_text,
        existing_parts,
    ):
        """
        判断候选信息是否已经被已有标题表达。

        只做通用文本包含判断，
        不包含具体产品规则。
        """

        if not new_text:
            return False


        def normalize_words(text):

            words = re.findall(
                r"[A-Za-z0-9\-]+",
                str(text).lower(),
            )


            ignore_words = {
                "with",
                "for",
                "and",
                "the",
                "a",
                "an",
            }


            result = set()


            for word in words:

                if not word:
                    continue


                if word in ignore_words:
                    continue


                # 轻量单复数归一化
                # heads -> head
                # buttons -> button
                if (
                    len(word) > 4
                    and
                    word.endswith("s")
                    and
                    not word.endswith(
                        (
                            "ss",
                            "us",
                            "is",
                        )
                    )
                ):

                    word = word[:-1]


                result.add(
                    word
                )


            return result


        new_words = normalize_words(
            new_text
        )


        if not new_words:
            return False


        for existing in existing_parts:

            existing_words = normalize_words(
                existing
            )


            if not existing_words:
                continue


            # 完全一致
            if new_words == existing_words:

                return True


            # 新信息已经完整包含于已有信息
            if new_words.issubset(
                existing_words
            ):

                return True


        return False
    @staticmethod
    def generate(
        profile: dict,
    ) -> dict:
        """
        V4.0 Final Title Constraint Solver

        Hard rules:
        - 61 <= final title <= 75
        - verified product IDENTITY must be present
        - verified COMPATIBILITY must be present when available
        - multi-unit quantity is a fixed compact prefix
        - no invented facts

        Architecture:
        Strategy decides semantics/value.
        This solver performs deterministic final allocation and repair.
        """

        if not isinstance(profile, dict):
            raise ValueError(
                "TitleGenerator profile must be a dictionary"
            )

        title_strategy = profile.get(
            "title_strategy",
            {},
        )

        strategy_input = profile.get(
            "title_strategy_input",
            {},
        )

        if not isinstance(title_strategy, dict):
            title_strategy = {}

        if not isinstance(strategy_input, dict):
            strategy_input = {}

        candidates = title_strategy.get(
            "title_candidates",
            [],
        )

        if not isinstance(candidates, list):
            candidates = []

        if not candidates:
            raise ValueError(
                "TitleGenerator V4 requires title_strategy.title_candidates"
            )

        # =================================================
        # Helpers
        # =================================================

        def normalize_text(value):
            if value is None:
                return ""

            return re.sub(
                r"\s+",
                " ",
                str(value).strip(),
            )


        def norm_key(value):
            return normalize_text(value).casefold()


        def words(value):
            return [
                token.casefold()
                for token in re.findall(
                    r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*",
                    normalize_text(value),
                )
                if token
            ]


        def compact_quantity(value):
            text_value = normalize_text(value)

            match = re.match(
                r"^\s*(\d+)\s*(?:x|pc|pcs|piece|pieces|set|sets)?\b",
                text_value,
                flags=re.IGNORECASE,
            )

            if not match:
                return ""

            try:
                count = int(
                    match.group(1)
                )
            except Exception:
                return ""

            if count <= 1:
                return ""

            return f"{count}pcs"


        def safe_number(value, default=0.0):
            try:
                return float(
                    value
                    if value is not None
                    else default
                )
            except Exception:
                return float(default)


        def candidate_value(candidate):
            incremental = candidate.get(
                "incremental_value",
                {},
            )

            if not isinstance(incremental, dict):
                incremental = {}

            adjusted_score = safe_number(
                candidate.get(
                    "adjusted_score",
                    candidate.get(
                        "final_score",
                        0,
                    ),
                )
            )

            selection_value = safe_number(
                incremental.get(
                    "selection_value",
                    0,
                )
            )

            new_information = safe_number(
                incremental.get(
                    "new_information",
                    0,
                )
            )

            redundancy_penalty = safe_number(
                incremental.get(
                    "redundancy_penalty",
                    0,
                )
            )

            return (
                adjusted_score * 0.55
                +
                selection_value * 0.25
                +
                new_information * 0.20
                -
                redundancy_penalty * 0.15
            )


        priority_rank = {
            "S": 0,
            "A": 1,
            "B": 2,
            "C": 3,
            "D": 4,
        }

        type_rank = {
            "IDENTITY": 0,
            "COMPATIBILITY": 1,
            "MODEL": 2,
            "PART_NUMBER": 2,
            "SPECIFICATION": 3,
            "FEATURE": 4,
            "MATERIAL": 4,
            "SEARCH_TERM": 5,
            "USAGE": 6,
            "OTHER": 7,
        }


        def candidate_sort_key(item):
            return (
                priority_rank.get(
                    item.get(
                        "priority",
                        "C",
                    ),
                    5,
                ),
                type_rank.get(
                    item.get(
                        "type",
                        "OTHER",
                    ),
                    7,
                ),
                -safe_number(
                    item.get(
                        "value",
                        0,
                    )
                ),
                len(
                    normalize_text(
                        item.get(
                            "text",
                            "",
                        )
                    )
                ),
            )


        # =================================================
        # Strategy exclusions
        # =================================================

        strategy_excludes = title_strategy.get(
            "exclude",
            [],
        )

        if not isinstance(strategy_excludes, list):
            strategy_excludes = []

        excluded_keys = {
            norm_key(item)
            for item in strategy_excludes
            if norm_key(item)
        }


        # =================================================
        # Locked mandatory facts
        # =================================================

        locked = strategy_input.get(
            "locked",
            {},
        )

        if not isinstance(locked, dict):
            locked = {}

        locked_identity = locked.get(
            "identity",
            {},
        )

        if not isinstance(locked_identity, dict):
            locked_identity = {}

        locked_compatibility = locked.get(
            "compatibility",
            {},
        )

        if not isinstance(locked_compatibility, dict):
            locked_compatibility = {}

        locked_models = locked.get(
            "models",
            {},
        )

        if not isinstance(locked_models, dict):
            locked_models = {}

        identity_candidate = next(
            (
                candidate
                for candidate in candidates
                if (
                    isinstance(candidate, dict)
                    and
                    normalize_text(
                        candidate.get(
                            "type",
                            "",
                        )
                    ).upper()
                    ==
                    "IDENTITY"
                )
            ),
            None,
        )

        compatibility_candidate = next(
            (
                candidate
                for candidate in candidates
                if (
                    isinstance(candidate, dict)
                    and
                    normalize_text(
                        candidate.get(
                            "type",
                            "",
                        )
                    ).upper()
                    ==
                    "COMPATIBILITY"
                )
            ),
            None,
        )

        identity_full = (
            normalize_text(
                locked_identity.get(
                    "text",
                    "",
                )
            )
            or
            normalize_text(
                (
                    identity_candidate
                    or
                    {}
                ).get(
                    "text",
                    "",
                )
            )
        )

        identity_short = normalize_text(
            (
                identity_candidate
                or
                {}
            ).get(
                "short_text",
                "",
            )
        )

        if (
            not identity_short
            or
            len(identity_short)
            >=
            len(identity_full)
        ):
            identity_short = ""

        compatibility_full = (
            normalize_text(
                locked_compatibility.get(
                    "phrase",
                    "",
                )
            )
            or
            normalize_text(
                (
                    compatibility_candidate
                    or
                    {}
                ).get(
                    "text",
                    "",
                )
            )
        )

        compatibility_brands = locked_compatibility.get(
            "brands",
            [],
        )

        if not isinstance(compatibility_brands, list):
            compatibility_brands = []

        compatibility_brands = [
            normalize_text(brand)
            for brand in compatibility_brands
            if normalize_text(brand)
        ]

        compatibility_short = normalize_text(
            (
                compatibility_candidate
                or
                {}
            ).get(
                "short_text",
                "",
            )
        )

        if (
            compatibility_short
            and
            not compatibility_short.casefold().startswith(
                "compatible with "
            )
        ):
            compatibility_short = ""

        # Deterministic emergency compatibility compression:
        # keep the highest-priority first verified compatible brand.
        compatibility_first_brand = ""

        if compatibility_brands:
            compatibility_first_brand = (
                "Compatible with "
                +
                compatibility_brands[0]
            )

        # =================================================
        # Verified quantity
        # =================================================

        quantity_text = ""

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            if normalize_text(
                candidate.get(
                    "type",
                    "",
                )
            ).upper() != "QUANTITY":
                continue

            quantity_text = compact_quantity(
                candidate.get(
                    "text",
                    "",
                )
            )

            if quantity_text:
                break

        if not quantity_text:
            confirmed_facts = strategy_input.get(
                "confirmed_facts",
                {},
            )

            if isinstance(confirmed_facts, dict):
                quantity_text = compact_quantity(
                    confirmed_facts.get(
                        "quantity",
                        "",
                    )
                )

        # =================================================
        # Mandatory core builder
        # =================================================

        core_variants = []

        identity_variants = [
            identity_full,
        ]

        if identity_short:
            identity_variants.append(
                identity_short
            )

        # V4.0 conservative syntax compression:
        # replacing standalone "and" with "&" preserves the same product
        # meaning while saving two characters. This is used only as another
        # candidate representation; it never changes the locked identity.
        for identity_variant_source in list(
            identity_variants
        ):
            ampersand_variant = re.sub(
                r"\band\b",
                "&",
                identity_variant_source,
                flags=re.IGNORECASE,
            )

            ampersand_variant = normalize_text(
                ampersand_variant
            )

            if (
                ampersand_variant
                and
                ampersand_variant
                !=
                identity_variant_source
                and
                ampersand_variant
                not in
                identity_variants
            ):
                identity_variants.append(
                    ampersand_variant
                )

        compatibility_variants = [
            compatibility_full,
        ] if compatibility_full else [""]

        if (
            compatibility_short
            and
            compatibility_short not in compatibility_variants
        ):
            compatibility_variants.append(
                compatibility_short
            )

        if (
            compatibility_first_brand
            and
            compatibility_first_brand not in compatibility_variants
        ):
            compatibility_variants.append(
                compatibility_first_brand
            )

        for identity_variant in identity_variants:
            for compatibility_variant in compatibility_variants:

                parts = [
                    part
                    for part in [
                        quantity_text,
                        identity_variant,
                        compatibility_variant,
                    ]
                    if part
                ]

                title_value = " ".join(parts)

                if len(title_value) <= 75:
                    core_variants.append(
                        {
                            "parts":
                                parts,
                            "identity":
                                identity_variant,
                            "compatibility":
                                compatibility_variant,
                            "length":
                                len(title_value),
                            "identity_is_short":
                                bool(
                                    identity_short
                                    and
                                    identity_variant
                                    ==
                                    identity_short
                                ),
                            "compatibility_is_compressed":
                                bool(
                                    compatibility_full
                                    and
                                    compatibility_variant
                                    !=
                                    compatibility_full
                                ),
                        }
                    )

        if not core_variants:
            # No safe way to satisfy mandatory identity+compatibility under 75.
            # Preserve identity first, then shortest verified compatibility.
            emergency_parts = [
                part
                for part in [
                    quantity_text,
                    identity_short
                    or
                    identity_full,
                    compatibility_first_brand
                    or
                    compatibility_short
                    or
                    compatibility_full,
                ]
                if part
            ]

            emergency_title = " ".join(
                emergency_parts
            )

            if len(emergency_title) > 75:
                emergency_title = (
                    TitleGenerator.limit_length(
                        emergency_title,
                        75,
                    )
                )

            blocked_words = (
                TitleGenerator.check_blocked_words(
                    emergency_title
                )
            )

            return {
                "title":
                    emergency_title,
                "selected_models":
                    [],
                "removed_models":
                    [],
                "character_count":
                    len(
                        emergency_title
                    ),
                "validation": {
                    "length_ok":
                        False,
                    "min_length_ok":
                        len(
                            emergency_title
                        )
                        >=
                        61,
                    "max_length_ok":
                        len(
                            emergency_title
                        )
                        <=
                        75,
                    "identity_present":
                        bool(identity_full),
                    "compatibility_required":
                        bool(compatibility_full),
                    "compatibility_present":
                        bool(
                            not compatibility_full
                            or
                            (
                                compatibility_first_brand
                                and
                                compatibility_first_brand.casefold()
                                in
                                emergency_title.casefold()
                            )
                            or
                            (
                                compatibility_full
                                and
                                compatibility_full.casefold()
                                in
                                emergency_title.casefold()
                            )
                        ),
                    "hard_constraints_ok":
                        False,
                    "hard_constraint_errors": [
                        "mandatory_core_exceeds_75_characters"
                    ],
                    "compliance_ok":
                        len(blocked_words)
                        ==
                        0,
                    "insufficient_verified_facts":
                        False,
                },
                "blocked_words":
                    blocked_words,
                "brand_check":
                    "failed",
                "generator_version":
                    "V4.0-final-title-constraint-solver",
                "budget_parts":
                    emergency_parts,
                "accepted_candidates":
                    [],
                "rejected_candidates":
                    [],
                "budget_used":
                    len(emergency_title),
                "budget_remaining":
                    max(
                        0,
                        75
                        -
                        len(emergency_title),
                    ),
                "solver": {
                    "status":
                        "mandatory_core_conflict",
                    "repair_applied":
                        True,
                },
            }

        # Prefer the most complete core that still leaves room.
        # Full identity / full compatibility win when possible.
        core_variants.sort(
            key=lambda item: (
                item[
                    "identity_is_short"
                ],
                item[
                    "compatibility_is_compressed"
                ],
                -item[
                    "length"
                ],
            )
        )

        core = core_variants[0]

        # =================================================
        # Candidate pool
        # =================================================

        pool = []
        seen_pool = set()


        def add_pool_item(
            text_value,
            candidate_type="OTHER",
            priority="C",
            value=30.0,
            source="verified_profile",
            short_text="",
            original_index=None,
        ):
            text_value = normalize_text(
                text_value
            )

            short_text = normalize_text(
                short_text
            )

            if not text_value:
                return

            key = norm_key(
                text_value
            )

            if not key:
                return

            if key in excluded_keys:
                return

            if key in seen_pool:
                return

            mandatory_keys = {
                norm_key(
                    core.get(
                        "identity",
                        "",
                    )
                ),
                norm_key(
                    core.get(
                        "compatibility",
                        "",
                    )
                ),
                norm_key(
                    quantity_text
                ),
            }

            if key in mandatory_keys:
                return

            seen_pool.add(
                key
            )

            pool.append(
                {
                    "text":
                        text_value,
                    "short_text":
                        short_text,
                    "type":
                        normalize_text(
                            candidate_type
                        ).upper()
                        or
                        "OTHER",
                    "priority":
                        normalize_text(
                            priority
                        ).upper()
                        or
                        "C",
                    "value":
                        safe_number(
                            value,
                            30,
                        ),
                    "source":
                        source,
                    "original_index":
                        original_index,
                }
            )


        # Strategy candidates remain the primary pool.
        for index, candidate in enumerate(
            candidates
        ):
            if not isinstance(candidate, dict):
                continue

            candidate_type = normalize_text(
                candidate.get(
                    "type",
                    "OTHER",
                )
            ).upper()

            if candidate_type in {
                "IDENTITY",
                "COMPATIBILITY",
                "QUANTITY",
            }:
                continue

            add_pool_item(
                candidate.get(
                    "text",
                    "",
                ),
                candidate_type=candidate_type,
                priority=normalize_text(
                    candidate.get(
                        "priority",
                        "C",
                    )
                ).upper(),
                value=candidate_value(
                    candidate
                ),
                source="title_strategy",
                short_text=candidate.get(
                    "short_text",
                    "",
                ),
                original_index=index,
            )

        # Verified fallback sources.
        candidate_facts = strategy_input.get(
            "candidate_facts",
            {},
        )

        if not isinstance(candidate_facts, dict):
            candidate_facts = {}

        confirmed_facts = strategy_input.get(
            "confirmed_facts",
            {},
        )

        if not isinstance(confirmed_facts, dict):
            confirmed_facts = {}

        purpose = strategy_input.get(
            "purpose",
            {},
        )

        if not isinstance(purpose, dict):
            purpose = {}


        def add_many(
            values,
            candidate_type,
            priority,
            value,
            source,
        ):
            if isinstance(values, list):
                source_values = values
            elif values:
                source_values = [values]
            else:
                source_values = []

            for value_item in source_values:
                add_pool_item(
                    value_item,
                    candidate_type,
                    priority,
                    value,
                    source,
                )


        add_many(
            candidate_facts.get(
                "locked_all_models",
                [],
            ),
            "MODEL",
            "A",
            78,
            "candidate_facts.locked_all_models",
        )

        add_many(
            candidate_facts.get(
                "locked_secondary_models",
                [],
            ),
            "MODEL",
            "B",
            68,
            "candidate_facts.locked_secondary_models",
        )

        add_many(
            confirmed_facts.get(
                "part_numbers",
                [],
            ),
            "PART_NUMBER",
            "A",
            78,
            "confirmed_facts.part_numbers",
        )

        add_many(
            candidate_facts.get(
                "important_specifications",
                [],
            ),
            "SPECIFICATION",
            "B",
            65,
            "candidate_facts.important_specifications",
        )

        add_many(
            candidate_facts.get(
                "specifications",
                [],
            ),
            "SPECIFICATION",
            "B",
            62,
            "candidate_facts.specifications",
        )

        add_many(
            candidate_facts.get(
                "design_features",
                [],
            ),
            "FEATURE",
            "B",
            55,
            "candidate_facts.design_features",
        )

        add_many(
            candidate_facts.get(
                "functional_features",
                [],
            ),
            "FEATURE",
            "B",
            55,
            "candidate_facts.functional_features",
        )

        add_many(
            confirmed_facts.get(
                "material",
                [],
            ),
            "MATERIAL",
            "B",
            50,
            "confirmed_facts.material",
        )

        add_many(
            confirmed_facts.get(
                "color",
                [],
            ),
            "FEATURE",
            "C",
            35,
            "confirmed_facts.color",
        )

        for field_name in (
            "dimensions",
            "voltage",
            "power",
            "weight",
        ):
            add_many(
                confirmed_facts.get(
                    field_name,
                    [],
                ),
                "SPECIFICATION",
                "B",
                58,
                f"confirmed_facts.{field_name}",
            )

        add_many(
            candidate_facts.get(
                "search_primary_keywords",
                [],
            ),
            "SEARCH_TERM",
            "B",
            52,
            "candidate_facts.search_primary_keywords",
        )

        add_many(
            candidate_facts.get(
                "search_secondary_keywords",
                [],
            ),
            "SEARCH_TERM",
            "C",
            42,
            "candidate_facts.search_secondary_keywords",
        )

        add_many(
            candidate_facts.get(
                "important_context",
                [],
            ),
            "USAGE",
            "C",
            40,
            "candidate_facts.important_context",
        )

        add_many(
            candidate_facts.get(
                "usage_scenarios",
                [],
            ),
            "USAGE",
            "C",
            35,
            "candidate_facts.usage_scenarios",
        )

        add_many(
            purpose.get(
                "primary_function",
                "",
            ),
            "FEATURE",
            "C",
            38,
            "purpose.primary_function",
        )

        add_many(
            purpose.get(
                "primary_use",
                "",
            ),
            "USAGE",
            "C",
            35,
            "purpose.primary_use",
        )

        title_plan = profile.get(
            "title_plan",
            {},
        )

        if isinstance(title_plan, dict):
            add_many(
                title_plan.get(
                    "search_terms",
                    [],
                ),
                "SEARCH_TERM",
                "C",
                38,
                "title_plan.search_terms",
            )

            add_many(
                title_plan.get(
                    "features",
                    [],
                ),
                "FEATURE",
                "C",
                38,
                "title_plan.features",
            )

        # =================================================
        # Core-specific mandatory primary model
        #
        # Model is high priority but never allowed to displace
        # identity or compatibility.
        # =================================================

        primary_model = normalize_text(
            locked_models.get(
                "primary",
                "",
            )
        )

        if (
            primary_model
            and
            norm_key(primary_model)
            not in {
                norm_key(identity_full),
                norm_key(core["identity"]),
            }
        ):
            add_pool_item(
                primary_model,
                "MODEL",
                "A",
                90,
                "locked.models.primary",
            )

        # =================================================
        # Redundancy / fact-value guards
        # =================================================

        def information_gain(
            text_value,
            existing_parts,
        ):
            new_words = set(
                words(
                    text_value
                )
            )

            if not new_words:
                return 0.0

            existing_words = set()

            for part in existing_parts:
                existing_words.update(
                    words(
                        part
                    )
                )

            novel = (
                new_words
                -
                existing_words
            )

            return (
                len(novel)
                /
                max(
                    1,
                    len(new_words),
                )
            )


        def choose_variant(
            item,
            current_parts,
        ):
            full_text = normalize_text(
                item.get(
                    "text",
                    "",
                )
            )

            short_text = normalize_text(
                item.get(
                    "short_text",
                    "",
                )
            )

            variants = []

            if full_text:
                variants.append(
                    (
                        full_text,
                        "text",
                    )
                )

            if (
                short_text
                and
                short_text != full_text
            ):
                variants.append(
                    (
                        short_text,
                        "short_text",
                    )
                )

            for variant, source_name in variants:
                candidate_title = " ".join(
                    current_parts
                    +
                    [variant]
                )

                if len(candidate_title) <= 75:
                    return (
                        variant,
                        source_name,
                    )

            return (
                "",
                "",
            )

        # =================================================
        # Deterministic global allocation
        # =================================================

        pool.sort(
            key=candidate_sort_key
        )

        selected_items = []
        rejected_items = []

        title_parts = list(
            core[
                "parts"
            ]
        )

        selected_models = []
        removed_models = []

        accepted_candidates = []

        # Record mandatory core.
        for part in title_parts:
            if part == quantity_text:
                item_type = "QUANTITY"
            elif part == core["identity"]:
                item_type = "IDENTITY"
            elif (
                core.get(
                    "compatibility",
                    ""
                )
                and
                part == core["compatibility"]
            ):
                item_type = "COMPATIBILITY"
            else:
                item_type = "OTHER"

            accepted_candidates.append(
                {
                    "index":
                        None,
                    "text":
                        part,
                    "short_text":
                        "",
                    "selected_text":
                        part,
                    "selected_source":
                        "mandatory_core",
                    "type":
                        item_type,
                    "priority":
                        (
                            "S"
                            if item_type
                            in {
                                "QUANTITY",
                                "IDENTITY",
                            }
                            else
                            "A"
                        ),
                    "required":
                        True,
                    "reason":
                        "mandatory_core",
                    "character_count_after":
                        len(
                            " ".join(
                                title_parts[
                                    :
                                    title_parts.index(part)
                                    +
                                    1
                                ]
                            )
                        ),
                }
            )

        # Pass 1:
        # use non-trivial incremental value candidates.
        deferred = []

        for item in pool:

            gain = information_gain(
                item[
                    "text"
                ],
                title_parts,
            )

            # Keep models/part numbers even when token-overlap is high.
            if (
                gain <= 0
                and
                item["type"]
                not in {
                    "MODEL",
                    "PART_NUMBER",
                }
            ):
                deferred.append(
                    item
                )
                continue

            selected_text, selected_source = (
                choose_variant(
                    item,
                    title_parts,
                )
            )

            if not selected_text:
                rejected_items.append(
                    {
                        **item,
                        "reason":
                            "character_budget",
                    }
                )

                if item["type"] in {
                    "MODEL",
                    "PART_NUMBER",
                }:
                    removed_models.append(
                        item["text"]
                    )

                continue

            title_parts.append(
                selected_text
            )

            selected_items.append(
                {
                    **item,
                    "selected_text":
                        selected_text,
                    "selected_source":
                        selected_source,
                }
            )

            if item["type"] in {
                "MODEL",
                "PART_NUMBER",
            }:
                selected_models.append(
                    selected_text
                )

            accepted_candidates.append(
                {
                    "index":
                        item.get(
                            "original_index"
                        ),
                    "text":
                        item[
                            "text"
                        ],
                    "short_text":
                        item.get(
                            "short_text",
                            "",
                        ),
                    "selected_text":
                        selected_text,
                    "selected_source":
                        selected_source,
                    "type":
                        item[
                            "type"
                        ],
                    "priority":
                        item[
                            "priority"
                        ],
                    "required":
                        False,
                    "reason":
                        "solver_selected",
                    "source":
                        item[
                            "source"
                        ],
                    "character_count_after":
                        len(
                            " ".join(
                                title_parts
                            )
                        ),
                }
            )

        # Pass 2:
        # If still below 61, verified SEO/search phrases may be used even
        # when partially redundant. This is allowed only because they come
        # from the verified candidate pool and no new fact is invented.
        if len(
            " ".join(
                title_parts
            )
        ) < 61:

            deferred.sort(
                key=candidate_sort_key
            )

            for item in deferred:

                if item["type"] not in {
                    "SEARCH_TERM",
                    "FEATURE",
                    "MATERIAL",
                    "USAGE",
                    "SPECIFICATION",
                }:
                    continue

                selected_text, selected_source = (
                    choose_variant(
                        item,
                        title_parts,
                    )
                )

                if not selected_text:
                    continue

                # Avoid exact duplicate phrase only.
                if norm_key(
                    selected_text
                ) in {
                    norm_key(part)
                    for part in title_parts
                }:
                    continue

                title_parts.append(
                    selected_text
                )

                selected_items.append(
                    {
                        **item,
                        "selected_text":
                            selected_text,
                        "selected_source":
                            selected_source,
                    }
                )

                accepted_candidates.append(
                    {
                        "index":
                            item.get(
                                "original_index"
                            ),
                        "text":
                            item[
                                "text"
                            ],
                        "short_text":
                            item.get(
                                "short_text",
                                "",
                            ),
                        "selected_text":
                            selected_text,
                        "selected_source":
                            selected_source,
                        "type":
                            item[
                                "type"
                            ],
                        "priority":
                            item[
                                "priority"
                            ],
                        "required":
                            False,
                        "reason":
                            "minimum_length_verified_completion",
                        "source":
                            item[
                                "source"
                            ],
                        "character_count_after":
                            len(
                                " ".join(
                                    title_parts
                                )
                            ),
                    }
                )

                if len(
                    " ".join(
                        title_parts
                    )
                ) >= 61:
                    break

        title = " ".join(
            title_parts
        )

        title = (
            TitleGenerator.clean_title(
                title
            )
        )

        if len(title) > 75:
            title = (
                TitleGenerator.limit_length(
                    title,
                    75,
                )
            )

        # =================================================
        # Hard validation against LOCKED facts, not merely
        # whichever candidates happened to survive.
        # =================================================

        title_fold = title.casefold()

        identity_variants_for_validation = [
            value
            for value in [
                identity_full,
                identity_short,
                core.get(
                    "identity",
                    "",
                ),
            ]
            if value
        ]

        identity_present = any(
            value.casefold()
            in title_fold
            for value in identity_variants_for_validation
        )

        compatibility_required = bool(
            compatibility_full
            or
            compatibility_brands
        )

        compatibility_validation_variants = [
            value
            for value in [
                compatibility_full,
                compatibility_short,
                compatibility_first_brand,
                core.get(
                    "compatibility",
                    "",
                ),
            ]
            if value
        ]

        compatibility_present = (
            True
            if not compatibility_required
            else
            any(
                value.casefold()
                in title_fold
                for value
                in compatibility_validation_variants
            )
        )

        min_length_ok = len(title) >= 61
        max_length_ok = len(title) <= 75

        insufficient_verified_facts = (
            not min_length_ok
            and
            len(
                " ".join(
                    title_parts
                )
            )
            <
            61
        )

        blocked_words = (
            TitleGenerator.check_blocked_words(
                title
            )
        )

        hard_constraint_errors = []

        if not min_length_ok:
            hard_constraint_errors.append(
                (
                    "insufficient_verified_facts"
                    if insufficient_verified_facts
                    else
                    "title_below_61_characters"
                )
            )

        if not max_length_ok:
            hard_constraint_errors.append(
                "title_above_75_characters"
            )

        if not identity_present:
            hard_constraint_errors.append(
                "identity_missing"
            )

        if (
            compatibility_required
            and
            not compatibility_present
        ):
            hard_constraint_errors.append(
                "compatibility_missing"
            )

        # Record non-selected model/part candidates.
        for item in pool:
            if item["type"] not in {
                "MODEL",
                "PART_NUMBER",
            }:
                continue

            if item["text"] in selected_models:
                continue

            if item["text"] not in removed_models:
                removed_models.append(
                    item["text"]
                )

        return {
            "title":
                title,

            "selected_models":
                selected_models,

            "removed_models":
                removed_models,

            "character_count":
                len(title),

            "validation": {
                "length_ok":
                    (
                        min_length_ok
                        and
                        max_length_ok
                    ),

                "min_length_ok":
                    min_length_ok,

                "max_length_ok":
                    max_length_ok,

                "identity_present":
                    identity_present,

                "compatibility_required":
                    compatibility_required,

                "compatibility_present":
                    compatibility_present,

                "hard_constraints_ok":
                    len(
                        hard_constraint_errors
                    )
                    ==
                    0,

                "hard_constraint_errors":
                    hard_constraint_errors,

                "compliance_ok":
                    len(
                        blocked_words
                    )
                    ==
                    0,

                "insufficient_verified_facts":
                    insufficient_verified_facts,
            },

            "blocked_words":
                blocked_words,

            "brand_check":
                (
                    "passed"
                    if compatibility_present
                    else
                    "failed"
                ),

            "generator_version":
                "V4.0-final-title-constraint-solver",

            "budget_parts":
                title_parts,

            "accepted_candidates":
                accepted_candidates,

            "rejected_candidates":
                rejected_items,

            "budget_used":
                len(title),

            "budget_remaining":
                max(
                    0,
                    75 - len(title),
                ),

            "solver": {
                "status":
                    (
                        "resolved"
                        if len(
                            hard_constraint_errors
                        )
                        ==
                        0
                        else
                        (
                            "insufficient_verified_facts"
                            if insufficient_verified_facts
                            else
                            "constraint_unresolved"
                        )
                    ),

                "mandatory_identity":
                    core.get(
                        "identity",
                        "",
                    ),

                "mandatory_compatibility":
                    core.get(
                        "compatibility",
                        "",
                    ),

                "identity_compressed":
                    core.get(
                        "identity_is_short",
                        False,
                    ),

                "compatibility_compressed":
                    core.get(
                        "compatibility_is_compressed",
                        False,
                    ),

                "candidate_pool_size":
                    len(pool),

                "selected_optional_count":
                    len(
                        selected_items
                    ),
            },
        }

    # =====================================================
    # 语义重复检测
    # 防止 Button / Cover / Shaver 等核心词重复
    # =====================================================

    @staticmethod
    def has_semantic_overlap(
        new_text,
        existing_parts,
    ):

        if not new_text:
            return False


        if not existing_parts:
            return False



        def extract_words(text):

            words = re.findall(
                r"[a-zA-Z0-9]+",
                str(text).lower()
            )


            ignore_words = {

                "compatible",
                "with",
                "for",
                "and",
                "the",

            }


            result = set()


            for word in words:

                # 太短词忽略
                if len(word) <= 2:
                    continue


                if word in ignore_words:
                    continue


                result.add(word)


            return result



        new_words = extract_words(
            new_text
        )


        if not new_words:

            return False



        for old in existing_parts:


            old_words = extract_words(
                old
            )


            overlap = (
                new_words
                &
                old_words
            )


            # 一个核心词重复即可认为可能重复
            if overlap:

                return True



        return False
    @staticmethod
    def clean_title(
        text: str,
    ):

        for word in TitleGenerator.BLOCKED_WORDS:

            text = re.sub(

                r"\b"
                +
                re.escape(word)
                +
                r"\b",

                "",

                text,

                flags=re.I,

            )


        text = re.sub(

            r"\s+",

            " ",

            text,

        )


        return text.strip()



    @staticmethod
    def format_title_case(
        text: str,
    ):

        words = text.split()


        small_words = [

            "with",
            "and",
            "for",
            "de",
            "para",
            "con",

        ]


        result = []


        for index, word in enumerate(words):

            if (
                index > 0
                and
                word.lower()
                in small_words
            ):

                result.append(
                    word.lower()
                )

            else:

                result.append(
                    word.capitalize()
                )


        return " ".join(result)

    @staticmethod
    def compress_title_parts(
        parts,
        max_length=75,
        priority_parts=None,
    ):

        if len(
            " ".join(parts)
        ) <= max_length:

            return parts



        result = []


        # 第一优先级：
        # 产品身份

        for part in parts:

            if len(result) == 0:

                result.append(
                    part
                )



        # 第二优先级：
        # 型号

        for part in parts:

            text = str(
                part
            )


            if re.search(
                r"[A-Za-z]+\d+",
                text
            ):

                if text not in result:

                    result.append(
                        text
                    )
        # 第三优先级：
        # 标题高价值属性

        if priority_parts:

            for part in priority_parts:

                if part in parts:

                    if part not in result:

                        result.append(
                            part
                        )


        # 第四优先级：
        # Compatible with 品牌

        for part in parts:

            if "Compatible with" in str(part):

                if part not in result:

                    result.append(
                        part
                    )



        # 第五优先级：
        # 其他卖点

        for part in parts:

            if part not in result:

                if len(
                    " ".join(result+[part])
                ) <= max_length:

                    result.append(
                        part
                    )



        return result
    @staticmethod
    def protect_compatibility_phrases(
        parts
    ):

        protected = []

        for part in parts:

            text = str(part)

            if text.startswith(
                "Compatible with"
            ):

                protected.append(
                    text.replace(
                        " ",
                        "_",
                    )
                )

            else:

                protected.append(
                    text
                )

        return protected
    @staticmethod
    def limit_length(
        text: str,
        max_length: int = 75,
    ):

        if len(text) <= max_length:

            return text


        words = text.split()


        result = []


        length = 0


        for word in words:

            if (
                length
                +
                len(word)
                +
                1
                >
                max_length
            ):

                break


            result.append(
                word
            )


            length += (
                len(word)
                +
                1
            )


        return " ".join(result)



    @staticmethod
    def check_blocked_words(
        text: str,
    ):

        found = []


        for word in TitleGenerator.BLOCKED_WORDS:

            if re.search(

                r"\b"
                +
                re.escape(word)
                +
                r"\b",

                text,

                flags=re.I,

            ):

                found.append(
                    word
                )


        return found
