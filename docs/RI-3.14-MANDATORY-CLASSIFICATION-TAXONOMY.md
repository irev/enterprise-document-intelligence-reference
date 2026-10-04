# RI-3.14 — Mandatory Classification Taxonomy

Classification now requires an explicit DocumentTaxonomy at the application boundary.

There is no compatibility path that permits classifier output to bypass taxonomy validation. Every classification invocation therefore has a selected label space and taxonomy version before confidence or abstention logic is evaluated.

This closes the transitional compatibility allowance introduced in RI-3.13. Provider/model output remains prediction data; the platform-owned taxonomy defines which canonical document types can exist.
