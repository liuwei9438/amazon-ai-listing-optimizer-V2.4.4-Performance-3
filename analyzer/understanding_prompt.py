from __future__ import annotations

import json

from dataclasses import asdict, is_dataclass

from typing import Any



SYSTEM_PROMPT = """
You are the product understanding layer of an Amazon listing system.

Your task is to analyze the product source information and return ONLY structured product data matching the provided JSON schema.

Rules:

- Do not write titles, bullets, descriptions, or marketing copy.
- Preserve source facts exactly.
- Never invent missing information.
- Use empty strings or empty arrays when information is unavailable.
- Separate product identity, features, usage scenarios, specifications, and identifiers.
- Treat third-party brands as compatibility references unless ownership is proven.
- Never accept claims such as original, genuine, official, OEM, authentic as verified facts.

Return only JSON matching the schema.
""".strip()



def _record_dict(
    record: Any,
) -> dict[str, Any]:


    if is_dataclass(record):

        return asdict(record)


    if isinstance(
        record,
        dict,
    ):

        return dict(record)


    if hasattr(
        record,
        "__dict__",
    ):

        return dict(
            vars(record)
        )


    return {
        "value":
            str(record)
    }




def build_user_prompt(
    record: Any,
    fact_lock: dict[str, Any],
    profile_template: dict[str, Any],
) -> str:


    source = _record_dict(
        record
    )
    return f"""
Analyze the SOURCE as one product and fill the complete Product Profile.


IMPORTANT RULES:


## 1. Fact Protection

Only use information directly supported by SOURCE.

Do not invent:

- quantity
- material
- color
- dimensions
- voltage
- power
- package contents
- compatible models
- part numbers
- product functions
- usage scenarios


If information is missing:

Use:

- empty string
- empty list



## 2. Product Identity Classification


Separate information into:


## 2. Product Identity Classification


Separate product identity information into different levels.


product_identity.name:

The core product name only.

This is the direct name of the product itself.

Do not include:

- usage scenarios
- target users
- materials
- marketing words
- compatibility claims
- application descriptions

title_product_identity:

Select exactly ONE authoritative product identity
for downstream Amazon title generation.

This field must contain the single best expression of:

"What exactly is the customer buying?"

Do not return alternative product identities.

Do not return a list.

Do not combine several synonymous product names.

The selected title_product_identity becomes the authoritative
product identity for all downstream title decisions.


IDENTITY SELECTION PRINCIPLE:

When multiple valid ways of describing the product exist,
evaluate them and select the ONE expression that provides
the strongest overall product identification.

Evaluate possible identity expressions in this order:

1. Product identification accuracy

Does the expression correctly identify
the actual physical product being sold?

An expression that identifies the wrong object,
a broader category, or only part of the sold product
must not be selected.


2. Product identity completeness

Does the expression communicate enough information
for a customer to understand what the product actually is?

Prefer an identity that fully describes the sold item
over one that communicates only a partial product concept.


3. Identity boundary correctness

Prefer an identity that keeps
independent product attributes separate.

A longer expression is NOT more complete
if its extra words actually belong to:

- quantity
- compatibility
- model
- part number
- specification
- material
- color
- feature

Completeness means complete product identity,
not complete product information.


4. Necessary device or application context

Determine whether the product name alone is sufficient.

If customers need device, machine, equipment,
or application context to understand what the product is,
include that context in title_product_identity.
CONTEXT NECESSITY TEST:

Generic device or application context may remain
inside title_product_identity only when removing it
would make the product identity materially ambiguous
or incomplete.

Use the minimum context necessary.

Do not include:

- a specific compatible brand
- a specific compatible model
- a compatibility phrase

merely to make the identity appear more complete.

Necessary generic context describes
what kind of product this is.

Compatibility describes
what specific brand, model, machine,
or platform the product fits.

Do not confuse these two roles.
Include only context that materially improves
product identification.

Do not include context merely because it appears in SOURCE.


5. Customer search relevance

Among identities that are equally accurate and complete,
prefer the expression that most naturally matches
how customers would identify or search for the product.


6. Character efficiency

Only after accuracy, completeness, necessary context,
and search relevance are satisfied,
prefer the more character-efficient expression.

Never choose a shorter identity if shortening it
reduces product identification accuracy or completeness.


OVER-BROAD IDENTITY RULE:

Do not select an expression that only describes
a broad category or generic product group.

Examples of overly broad identity concepts include
generic ideas such as:

- parts
- accessories
- components
- replacement parts

when the actual sold product can be identified more precisely.


OVER-NARROW IDENTITY RULE:

Do not select an identity that describes only
a partial product concept when necessary context is missing.

If the core product type could reasonably refer
to products used with many different devices or applications,
include enough verified device/application context
to make the sold product clear.


IDENTITY BOUNDARY:

title_product_identity may contain:

- the actual core product type
- necessary product-defining component type
- necessary device/application context
IDENTITY SEPARABILITY TEST:

Before finalizing title_product_identity,
check whether each piece of information belongs
to the physical product identity itself
or to an independent downstream attribute.

Ask:

"Can this information be represented independently
without changing what the physical product fundamentally is?"

If YES,
do not absorb it into title_product_identity.

Independent downstream information includes:

- quantity
- compatibility brand
- compatible model
- part number
- series number
- dimensions
- color
- material
- voltage
- power
- technical specifications
- functional features

These facts must remain separate
so downstream title strategy can evaluate them independently.
title_product_identity must not contain:

- package quantity
- compatible brand names
- compatibility wording
- compatible model numbers
- part numbers unless inseparable from product identity
- material unless inseparable from product identity
- color
- dimensions
- voltage
- power
- secondary features
- marketing wording
- seller-created categories
- promotional wording


SINGLE IDENTITY RULE:

There must be exactly ONE title_product_identity.

Other valid synonymous, broader, narrower,
or alternative search expressions must not be merged
into title_product_identity.

They may remain available elsewhere in the Product Profile
for:

- bullet points
- SEO keywords
- backend search terms
- supporting product information

but they must not become additional title identities.


FINAL CHECK:

Before returning title_product_identity, verify:

1. Does it accurately identify the sold product?
2. Is it sufficiently complete?
3. Does it contain necessary product context?
4. Is it neither too broad nor too narrow?
5. Is it natural for customer search?
6. Does it exclude package quantity?
7. Does it exclude compatibility brands and wording?
8. Does it exclude compatible models and part numbers?
9. Does it exclude independent specifications and features?
10. Does every remaining context word help identify
    what the physical product actually is?

If a shorter identity fails any of these checks,
use the more complete identity.



context:

Include:

- device context
- application object
- environment
- target user


design_features:

Only physical design characteristics.


functional_features:

Only confirmed product functions.


usage_scenarios:

Only supported usage situations.



## 3. Identifier Classification


Analyze numbers, codes, and alphanumeric values according to their actual product role.


Do not classify values only because they contain numbers, letters, or special characters.


Classify into:


model_number:

A value that identifies a specific product model, device model, or compatible machine model.

A model_number should help users distinguish one product identity from another.


part_number:

A manufacturer-defined or replacement part identifier.


series_number:

A product family or series identifier.


unknown_code:

A code whose meaning cannot be safely determined.

Important quantity classification rule:

Do not classify package quantity as identifiers.

Examples:

- 2PCS
- 4PCS
- 6PCS
- 12 pieces
- 3 sets

These values represent package quantity and must be classified as quantity information.

They should not enter:

- model_numbers
- part_numbers
- series_numbers
- unknown_codes

Only classify values as identifiers when they identify a specific product model, part number, or product code.

Decision process:


First determine whether the value identifies a specific product identity.


If the value only describes:

- product capability
- technical performance
- feature level
- configuration count
- protection level
- operating parameter
- measurable specification

do not classify it as model_number.


Classify those values as specification or unknown_code according to their meaning.


Do not put:

- voltage
- power
- dimensions
- weight
- technical specifications

into identifiers.


Only verified product identity information can enter:

- model_numbers
- part_numbers
- series_numbers



## 4. Specification Extraction


Extract measurable facts separately.


Include:


dimensions:

Size information.


weight:

Weight information.


voltage:

Voltage information.


power:

Power rating.


capacity:

Capacity information.



## 5. Brand Handling


For brand information:


If the product is compatible with a third-party brand:

relationship:

unbranded_compatible


Use:

Compatible with + brand


Do not treat:

- original
- genuine
- official
- OEM
- authentic

as verified facts.



## 6. Compatibility


Only keep compatibility information directly supported by SOURCE.


Do not invent:

- models
- brands
- replacements



## 7. Feature Classification


Classify features into:


materials:

Confirmed materials only.


design_features:

Physical structure only.


functional_features:

Confirmed functions only.


specifications:

Measured values or technical parameters.


usage_scenarios:

Supported usage only.



Do not convert assumptions into features.

## Title Information Selection


The Amazon title has limited space.

Select the most valuable information that should appear in the title.


priority_attributes:

Select important attributes that help customers distinguish or choose the product.

Prioritize information that is difficult to recover after removing it from the title.

Examples:

- package quantity
- special configuration
- important design characteristics
- version differences


important_specifications:

Select technical specifications that customers commonly search for.

Examples:

- power
- capacity
- size
- important model-related specifications


important_quantity:

Always keep package quantity when quantity is clearly provided in SOURCE.

Package quantity should be considered a high-priority title attribute when it affects customer purchase decisions.

Quantity is especially important for:

- replacement parts
- accessories
- multi-piece packages
- consumable products

Examples:

- 2PCS Filter
- 6PCS Tuning Pegs
- 4PCS Replacement Blades


important_context:

Keep important product context required for customer understanding.

Examples:

- device type
- application object
- special usage context


important_compatibility:

Keep important compatibility information supported by SOURCE.

Examples:

- compatible brands
- compatible device families
- important compatible models


Do not select:

- generic seller categories
- marketing words
- unsupported claims
- low-value information that does not help search relevance or purchase decision


The goal is:

Choose the highest-value facts for a limited Amazon title length.

## 8. Search Strategy

Generate search strategy only from verified information.

Primary search identity should be derived from buyer_search_identity when available.

title_identifiers:

Only high-value identifiers suitable for title.
Title identifiers must come only from verified model_number, part_number, or series_number.

Do not use:
- specifications
- features
- performance values
- marketing descriptions

bullet_identifiers:

Additional compatibility identifiers.


backend_identifiers:

Remaining verified identifiers.


Do not invent keywords.



## 9. Compliance


Identify risky claims:


- original
- genuine
- official
- OEM
- authentic
- authorized
- best seller
- #1
- premium quality


Return compliance information.



## 10. Output


Return every field required by PROFILE TEMPLATE.


The output must match the JSON schema exactly.



SOURCE:

{json.dumps(
    source,
    ensure_ascii=False,
    default=str
)}


VERIFIED FACT LOCK:

{json.dumps(
    fact_lock,
    ensure_ascii=False
)}


PROFILE TEMPLATE:

{json.dumps(
    profile_template,
    ensure_ascii=False
)}

""".strip()
