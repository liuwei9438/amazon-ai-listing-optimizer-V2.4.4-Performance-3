from __future__ import annotations

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



        # 保留 AI 原始结果中未被否定的信息
        # 这里只更新确认项

        if model_values:

            compatibility["models"] = model_values


        if part_values:

            compatibility["part_numbers"] = part_values



        profile["compatibility"] = compatibility


        return profile
