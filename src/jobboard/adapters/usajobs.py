"""USAJOBS adapter (SPEC.md §3.3, Tier 2).

GET https://data.usajobs.gov/api/Search
Needs an API key header plus a User-Agent set to the registered email, both
from the environment. `PublicationStartDate` -> date_precision='exact'.
"""
