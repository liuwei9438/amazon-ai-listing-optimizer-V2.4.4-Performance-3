from __future__ import annotations


class StrategyInputBuilderError(Exception):
    pass


class StrategyInputBuilder:
    """
    Title Strategy Input Builder V1.0

    职责：
    - 为 Title Strategy 构造唯一、明确、无歧义的输入
    - 优先使用 normalized_knowledge
    - 保留已确认的事实、特征、规格和搜索意图
    - 不重新理解产品
    - 不重新决定 Identity
    - 不生成标题
    - 不做 Candidate 排序
    """

    SCHEMA_VERSION = "1.0"

    @staticmethod
    def _dict(
        value,
    ) -> dict:

        if isinstance(
            value,
            dict,
        ):
            return value

        return {}

    @staticmethod
    def _list(
        value,
    ) -> list:

        if isinstance(
            value,
            list,
        ):
            return value

        return []

    @staticmethod
    def _text(
        value,
    ) -> str:

        if value is None:
            return ""

        return " ".join(
            str(value)
            .strip()
            .split()
        )

    @staticmethod
    def build(
        profile: dict,
    ) -> dict:

        if not isinstance(
            profile,
            dict,
        ):

            raise StrategyInputBuilderError(
                "Profile must be a dictionary"
            )

        normalized = (
            StrategyInputBuilder._dict(
                profile.get(
                    "normalized_knowledge",
                    {},
                )
            )
        )

        product_knowledge = (
            StrategyInputBuilder._dict(
                profile.get(
                    "product_knowledge",
                    {},
                )
            )
        )

        # =============================================
        # Normalized / locked inputs
        # =============================================

        normalized_identity = (
            StrategyInputBuilder._dict(
                normalized.get(
                    "identity",
                    {},
                )
            )
        )

        normalized_compatibility = (
            StrategyInputBuilder._dict(
                normalized.get(
                    "compatibility",
                    {},
                )
            )
        )

        normalized_models = (
            StrategyInputBuilder._dict(
                normalized.get(
                    "models",
                    {},
                )
            )
        )

        # =============================================
        # Product Knowledge supporting information
        # =============================================

        title_information = (
            StrategyInputBuilder._dict(
                product_knowledge.get(
                    "title_information",
                    {},
                )
            )
        )

        feature_classification = (
            StrategyInputBuilder._dict(
                product_knowledge.get(
                    "feature_classification",
                    {},
                )
            )
        )

        facts = (
            StrategyInputBuilder._dict(
                product_knowledge.get(
                    "facts",
                    {},
                )
            )
        )

        purpose = (
            StrategyInputBuilder._dict(
                product_knowledge.get(
                    "purpose",
                    {},
                )
            )
        )

        seo = (
            StrategyInputBuilder._dict(
                product_knowledge.get(
                    "seo",
                    {},
                )
            )
        )

        compliance = (
            StrategyInputBuilder._dict(
                product_knowledge.get(
                    "compliance",
                    {},
                )
            )
        )

        # =============================================
        # Build clean strategy input
        # =============================================

        strategy_input = {
            "schema_version":
                StrategyInputBuilder.SCHEMA_VERSION,

            # -----------------------------------------
            # Locked decisions
            # Title Strategy不得重新决定
            # -----------------------------------------

            "locked": {

                "identity": {
                    "text":
                        StrategyInputBuilder._text(
                            normalized_identity.get(
                                "text",
                                "",
                            )
                        ),

                    "source":
                        StrategyInputBuilder._text(
                            normalized_identity.get(
                                "source",
                                "",
                            )
                        ),

                    "confidence":
                        normalized_identity.get(
                            "confidence",
                            0,
                        ),
                },

                "compatibility": {
                    "phrase":
                        StrategyInputBuilder._text(
                            normalized_compatibility.get(
                                "phrase",
                                "",
                            )
                        ),

                    "brands":
                        StrategyInputBuilder._list(
                            normalized_compatibility.get(
                                "brands",
                                [],
                            )
                        ),
                },

                "models": {
                    "all":
                        StrategyInputBuilder._list(
                            normalized_models.get(
                                "all",
                                [],
                            )
                        ),

                    "primary":
                        StrategyInputBuilder._text(
                            normalized_models.get(
                                "primary",
                                "",
                            )
                        ),

                    "secondary":
                        StrategyInputBuilder._list(
                            normalized_models.get(
                                "secondary",
                                [],
                            )
                        ),
                },
            },

            # -----------------------------------------
            # Candidate facts
            # Strategy可以评估优先级，
            # 但不能修改事实。
            # -----------------------------------------

            "candidate_facts": {

                "priority_attributes":
                    StrategyInputBuilder._list(
                        title_information.get(
                            "priority_attributes",
                            [],
                        )
                    ),

                "important_specifications":
                    StrategyInputBuilder._list(
                        title_information.get(
                            "important_specifications",
                            [],
                        )
                    ),

                "important_quantity":
                    StrategyInputBuilder._text(
                        title_information.get(
                            "important_quantity",
                            "",
                        )
                    ),

                "important_context":
                    StrategyInputBuilder._list(
                        title_information.get(
                            "important_context",
                            [],
                        )
                    ),

                "design_features":
                    StrategyInputBuilder._list(
                        feature_classification.get(
                            "design_features",
                            [],
                        )
                    ),

                "functional_features":
                    StrategyInputBuilder._list(
                        feature_classification.get(
                            "functional_features",
                            [],
                        )
                    ),

                "usage_scenarios":
                    StrategyInputBuilder._list(
                        feature_classification.get(
                            "usage_scenarios",
                            [],
                        )
                    ),

                "specifications":
                    StrategyInputBuilder._list(
                        feature_classification.get(
                            "specifications",
                            [],
                        )
                    ),
            },

            # -----------------------------------------
            # Confirmed facts
            # -----------------------------------------

            "confirmed_facts": {
                "quantity":
                    facts.get(
                        "quantity",
                        "",
                    ),

                "material":
                    facts.get(
                        "material",
                        [],
                    ),

                "color":
                    facts.get(
                        "color",
                        "",
                    ),

                "dimensions":
                    facts.get(
                        "dimensions",
                        "",
                    ),

                "voltage":
                    facts.get(
                        "voltage",
                        "",
                    ),

                "power":
                    facts.get(
                        "power",
                        "",
                    ),

                "weight":
                    facts.get(
                        "weight",
                        "",
                    ),

                "part_numbers":
                    facts.get(
                        "part_numbers",
                        [],
                    ),

                "package_contents":
                    facts.get(
                        "package_contents",
                        [],
                    ),
            },

            # -----------------------------------------
            # Purpose / search intent
            # -----------------------------------------

            "purpose": {
                "primary_function":
                    StrategyInputBuilder._text(
                        purpose.get(
                            "primary_function",
                            "",
                        )
                    ),

                "primary_use":
                    StrategyInputBuilder._text(
                        purpose.get(
                            "primary_use",
                            "",
                        )
                    ),
            },

            "search": {
                "intent":
                    StrategyInputBuilder._text(
                        seo.get(
                            "search_intent",
                            "",
                        )
                    ),

                "primary_keywords":
                    StrategyInputBuilder._list(
                        seo.get(
                            "primary_keywords",
                            [],
                        )
                    ),

                "secondary_keywords":
                    StrategyInputBuilder._list(
                        seo.get(
                            "secondary_keywords",
                            [],
                        )
                    ),
            },

            # -----------------------------------------
            # Compliance
            # -----------------------------------------

            "compliance": {
                "brand_relationship":
                    StrategyInputBuilder._text(
                        compliance.get(
                            "brand_relationship",
                            "",
                        )
                    ),

                "brand_usage_rule":
                    StrategyInputBuilder._text(
                        compliance.get(
                            "brand_usage_rule",
                            "",
                        )
                    ),

                "blocked_claims":
                    StrategyInputBuilder._list(
                        compliance.get(
                            "blocked_claims",
                            [],
                        )
                    ),
            },
        }

        # Identity 是 Strategy 必需数据。
        if not strategy_input[
            "locked"
        ][
            "identity"
        ][
            "text"
        ]:

            raise StrategyInputBuilderError(
                "Normalized identity is missing"
            )

        return strategy_input
