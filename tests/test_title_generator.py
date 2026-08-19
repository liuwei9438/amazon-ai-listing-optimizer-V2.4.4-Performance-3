from generator.title_generator import TitleGenerator


def test_title_generation():

    profile = {

        "basic_info": {
            "product_type": "Washing Machine Part",
            "main_function": "Start Button Power Drive Button"
        },

        "brand_info": {
            "relationship": "unbranded_compatible"
        },

        "compatibility": {
            "brands": [
                "LG"
            ],
            "models": [
                "WD-N10240D",
                "WD-T12360D",
                "A12355DS"
            ]
        },

        "seo": {

            "primary_keywords": [
                "washing machine start button"
            ]

        }

    }


    result = TitleGenerator.generate(profile)


    print(result)


    assert "Compatible with LG" in result["title"]

    assert "washing machine start button" in result["title"]

    assert result["validation"]["length_ok"]

    assert result["validation"]["compliance_ok"]
