from __future__ import annotations

import re
from typing import Any

from services import (
    OpenAIResponsesClient,
    AIClientError,
)

from .fact_lock import (
    build_fact_lock,
    validate_fact_lock,
)

from .product_profile_schema import (
    empty_profile,
    json_schema,
)

from .profile_validator import (
    normalize_profile,
    validate_profile,
)

from .understanding_prompt import (
    SYSTEM_PROMPT,
    build_user_prompt,
)

from .attribute_engine import (
    extract_basic_attributes,
)

from .attribute_validator import (
    validate_attributes,
    validate_compatibility,
)

from .identifier_classifier import (
    IdentifierClassifier,
    IdentifierClassificationError,
)



class UnderstandingError(
    RuntimeError
):
    pass




class ProductUnderstandingEngine:


    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4.1-mini"
    ):


        self.client = OpenAIResponsesClient(

            api_key=api_key,

            model=model,
            stage="product_understanding",

        )


        self.identifier_classifier = IdentifierClassifier(

            api_key=api_key,

            model=model,

        )



    def analyze(
        self,
        record: Any
    ) -> dict[str, Any]:


        expected_lock = build_fact_lock(
            record
        )


        prompt = build_user_prompt(

            record,

            expected_lock,

            empty_profile(),

        )


        try:

            raw = self.client.create_json(

                SYSTEM_PROMPT,

                prompt,

                json_schema(),

            )


        except AIClientError as exc:

            raise UnderstandingError(

                str(exc)

            ) from exc



        profile = normalize_profile(
            raw
        )


        # =================================================
        # Understanding Recovery
        # =================================================

        profile = self._recover_missing_product_type(
            profile
        )


        # =================================================
        # Identifier Classification
        # =================================================

        try:

            profile = self.classify_identifiers(
                profile,
                record,
            )


        except IdentifierClassificationError as exc:

            raise UnderstandingError(
                str(exc)
            ) from exc



        # =================================================
        # Deterministic Attributes
        # =================================================

        extracted_attributes = (
            extract_basic_attributes(
                record
            )
        )


        profile.setdefault(

            "attributes",

            {}

        )


        profile["attributes"].update(

            extracted_attributes

        )


        profile["attributes"] = (

            validate_attributes(

                profile["attributes"]

            )

        )



        # =================================================
        # Compatibility Validation
        # =================================================

        profile.setdefault(

            "compatibility",

            {}

        )


        profile["compatibility"] = (

            validate_compatibility(

                profile["compatibility"]

            )

        )



        # =================================================
        # Source Identity
        # =================================================

        profile["source_identity"] = {


            "sku":

                getattr(

                    record,

                    "sku",

                    ""

                ),


            "parent_sku":

                getattr(

                    record,

                    "parent_sku",

                    ""

                ),


            "source_row_index":

                getattr(

                    record,

                    "row_number",

                    None

                ),

        }



        # =================================================
        # Fact Lock
        # =================================================

        profile["fact_lock"] = expected_lock



        errors = (

            validate_profile(profile)

            +

            validate_fact_lock(

                profile,

                expected_lock,

            )

        )


        if errors:

            raise UnderstandingError(

                "；".join(errors)

            )



        return profile



    # =====================================================
    # Understanding Identity Recovery
    # =====================================================

    @staticmethod
    def _recover_missing_product_type(
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Recover a missing basic_info.product_type from already
        identified, source-grounded product identity fields.

        Root cause:
        the first AI understanding call can occasionally identify the
        product correctly in product_identity / basic_info.product_name
        while leaving basic_info.product_type empty.  The previous validator
        treated that single blank field as a fatal product-level failure.

        Recovery order intentionally uses only fields already returned by
        the understanding stage; it does not invent a category or infer from
        arbitrary numbers/specifications.
        """

        if not isinstance(profile, dict):
            return profile

        basic = profile.setdefault(
            "basic_info",
            {},
        )

        if not isinstance(basic, dict):
            basic = {}
            profile["basic_info"] = basic

        current_type = str(
            basic.get("product_type")
            or ""
        ).strip()

        if current_type:
            return profile

        product_identity = profile.get(
            "product_identity",
            {},
        )

        if not isinstance(product_identity, dict):
            product_identity = {}

        candidates = [
            basic.get("product_name"),
            product_identity.get("name"),
            product_identity.get("title_product_identity"),
            product_identity.get("buyer_search_identity"),
        ]

        recovered = ""

        for value in candidates:
            value = str(value or "").strip()
            if value:
                recovered = value
                break

        if not recovered:
            return profile

        basic["product_type"] = recovered

        # Keep product_name populated as well when the AI returned identity
        # fields but omitted the mirrored basic_info name.
        if not str(basic.get("product_name") or "").strip():
            basic["product_name"] = recovered

        profile.setdefault(
            "understanding_recovery",
            {},
        )

        # product_profile_schema has additionalProperties=False for the AI
        # response, but this metadata is added only after schema parsing.  It
        # is useful in diagnostics and ignored by downstream knowledge code.
        profile["understanding_recovery"] = {
            "product_type_recovered": True,
            "recovered_product_type": recovered,
            "source": "existing_identity_field",
        }

        return profile


    # =====================================================
    # Contextual Numeric Model Recovery
    # =====================================================

    @staticmethod
    def _recover_numeric_compatibility_models(
        title: str,
        candidates: list[str],
        already_models: list[str],
    ) -> list[str]:
        """
        Recover source-supported bare numeric model numbers when the AI
        classifier is overly conservative.

        This is intentionally NOT "numbers = models".

        Recovery requires all of the following:
        1. The value is a bare 3-6 digit token.
        2. It appears in the source title.
        3. It appears inside a compatibility/model zone introduced by
           wording such as "for", "compatible with", or "fits".
        4. At least two such numeric candidates occur in that same zone.

        This handles real compatibility lists such as:
            "... OPC Drum for Canon iR 2520 2525 2530 2535 ..."
        while avoiding quantities, dimensions, voltage, power, and short
        family codes such as "34 35" that occur outside the compatibility
        zone.
        """

        title = str(title or "").strip()
        if not title:
            return list(already_models or [])

        lowered = title.casefold()

        # Use the LAST compatibility introducer. Product names/specifications
        # commonly appear earlier, while the fitment list normally follows it.
        cue_matches = list(
            re.finditer(
                r"\b(?:compatible\s+with|fits?|for)\b",
                lowered,
                flags=re.IGNORECASE,
            )
        )

        if not cue_matches:
            return list(already_models or [])

        zone_start = cue_matches[-1].end()
        compatibility_zone = title[zone_start:]

        numeric_candidates: list[str] = []

        for raw in candidates:
            value = str(raw or "").strip()

            # Bare numeric device models are normally 3-6 digits.
            # Units/quantities such as 10pcs, 60V, 30MM, 1-3cm do not match.
            if not re.fullmatch(r"\d{3,6}", value):
                continue

            if not re.search(
                rf"(?<!\w){re.escape(value)}(?!\w)",
                compatibility_zone,
                flags=re.IGNORECASE,
            ):
                continue

            numeric_candidates.append(value)

        # A single bare number remains ambiguous; let the AI classification
        # stand. A sequence of 2+ values is strong compatibility-list evidence.
        if len(numeric_candidates) < 2:
            return list(already_models or [])

        recovered = list(already_models or [])
        seen = {str(x).casefold() for x in recovered if x}

        for value in numeric_candidates:
            key = value.casefold()
            if key not in seen:
                recovered.append(value)
                seen.add(key)

        return recovered


    # =====================================================
    # Identifier Classification
    # =====================================================

    def classify_identifiers(
        self,
        profile: dict[str, Any],
        record: Any,
    ) -> dict[str, Any]:


        compatibility = profile.get(

            "compatibility",

            {}

        )


        if not isinstance(

            compatibility,

            dict

        ):

            compatibility = {}



        # =====================================================
        # V1.2 Identifier Candidate Protection
        #
        # Root cause fixed here:
        # The second-stage IdentifierClassifier previously received only
        # compatibility.models / compatibility.part_numbers produced by the
        # first AI understanding pass. If that pass omitted a source-supported
        # model (for example a long compatibility model list), the classifier
        # never had a chance to recover it and downstream Knowledge received
        # models=[].
        #
        # The deterministic Fact Lock already extracts source-supported
        # identifier candidates from the complete source. Merge those
        # candidates into the classifier input, then let IdentifierClassifier
        # decide their semantic role. This preserves Fact Protection:
        # - Fact Lock supplies only values present in SOURCE.
        # - IdentifierClassifier still decides model / part / spec / quantity.
        # - Nothing is inserted directly into compatibility without
        #   classification.
        # =====================================================

        fact_lock = build_fact_lock(
            record
        )

        candidates = []

        candidates.extend(
            compatibility.get(
                "models",
                []
            )
        )

        candidates.extend(
            compatibility.get(
                "part_numbers",
                []
            )
        )

        candidates.extend(
            fact_lock.get(
                "compatible_models",
                []
            )
        )

        candidates.extend(
            fact_lock.get(
                "part_numbers",
                []
            )
        )

        # Stable case-insensitive de-duplication. Keep first appearance so
        # source / AI ordering remains deterministic.
        unique_candidates = []
        seen_candidates = set()

        for value in candidates:

            value = str(
                value or ""
            ).strip()

            if not value:
                continue

            key = value.casefold()

            if key in seen_candidates:
                continue

            seen_candidates.add(
                key
            )

            unique_candidates.append(
                value
            )

        candidates = unique_candidates


        if not candidates:

            return profile



        product_context = {


            "title":

                getattr(

                    record,

                    "title",

                    ""

                ),


            "product_type":

                profile.get(

                    "basic_info",

                    {}

                ).get(

                    "product_type",

                    ""

                ),


            "main_function":

                profile.get(

                    "basic_info",

                    {}

                ).get(

                    "main_function",

                    ""

                ),


            "compatibility":

                compatibility,

        }



        result = (

            self.identifier_classifier.classify(

                product_context,

                candidates,

            )

        )



        model_values = []

        part_values = []



        for item in result.get(

            "identifier_results",

            []

        ):


            if item.get(

                "type"

            ) == "model_number":


                model_values.append(

                    item.get(

                        "value"

                    )

                )



            elif item.get(

                "type"

            ) == "part_number":


                part_values.append(

                    item.get(

                        "value"

                    )

                )



        # =====================================================
        # V1.3 Contextual Recovery
        #
        # Some valid device models are bare numbers. Even with the full title,
        # the AI classifier may conservatively return them as unknown.
        # Recover only numeric sequences that are source-supported and located
        # inside a clear compatibility zone.
        # =====================================================

        model_values = self._recover_numeric_compatibility_models(
            getattr(
                record,
                "title",
                ""
            ),
            candidates,
            model_values,
        )


        # 保留 AI 原始结果中未被否定的信息
        # 这里只更新确认项

        if model_values:

            compatibility["models"] = list(
                dict.fromkeys(
                    value
                    for value in model_values
                    if value
                )
            )


        if part_values:

            compatibility["part_numbers"] = list(
                dict.fromkeys(
                    value
                    for value in part_values
                    if value
                )
            )



        profile["compatibility"] = compatibility


        return profile
