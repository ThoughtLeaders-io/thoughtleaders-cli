#!/usr/bin/env python3
"""A keyword hint for a fact's sensitivity tier, so the extractor does not
have to tier anything.

The extractor's job is who is talking and what they said. Whether that is
``clinical``, ``children``, ``location``, ``lifestyle`` or ``none`` is decided
at the end of the pipeline: ``assemble_extracts.py`` attaches this hint to
every gem the extractor left untiered, the merge shard sees it as ``tier`` on
its input line and owns the final call, and ``merge_pass.py expand`` falls
back to it when the shard said nothing. The tiers and what they hold are
``evidence-rules.md``'s; this file only spots the obvious words.

The hint errs protective: a word that could be clinical is clinical, because
the merge pass may lower a tier it disagrees with but a fact that never gets
flagged is never looked at. ``children`` and ``location`` come first because
they are the tiers that never publish by default.
"""
from __future__ import annotations

import re

TIERS = ("none", "lifestyle", "clinical", "children", "location")

_CHILD = re.compile(r"\b(son|daughter|kid|kids|child|children|baby|toddler|twins|"
                    r"stepson|stepdaughter)\b", re.I)
_CHILD_DETAIL = re.compile(r"\b(named?|called|years? old|months? old|turned|birthday|"
                           r"school|grade|kindergarten|preschool|daycare|nursery)\b", re.I)
_LOCATION = re.compile(r"\b(street|avenue|boulevard|neighbou?rhood|suburb|address|"
                       r"zip code|postcode|apartment \d+|apt\.?|building|block|cul-de-sac|"
                       r"lives? (?:on|at)|next door to)\b", re.I)
_CLINICAL = re.compile(r"\b(diagnos\w*|disorder|adhd|autis\w*|depress\w*|anxiety|bipolar|"
                       r"ocd|ptsd|therap\w*|medicat\w*|meds|antidepress\w*|surger\w*|"
                       r"hospitali[sz]\w*|cancer|tumou?r|chemo\w*|disab\w*|wheelchair|"
                       r"fertil\w*|ivf|miscarr\w*|pregnan\w*|anorex\w*|bulimi\w*|addict\w*|"
                       r"rehab|sober|relapse\w*|seizure\w*|epilep\w*|diabet\w*|chronic|"
                       r"illness|syndrome|dyslex\w*|concussion\w*|prescri\w*|panic attack\w*|"
                       r"eating disorder|self-harm|suicid\w*)\b", re.I)
_LIFESTYLE = re.compile(r"\b(glasses|contacts|contact lens\w*|diet|vegan|vegetarian|keto|"
                        r"fasting|gym|workout\w*|work(?:s|ed|ing)? out|weight|pounds|kilos|"
                        r"sleep\w*|skincare|skin|allerg\w*|supplement\w*|protein|caffeine|"
                        r"smok\w*|drink\w*|alcohol|sunscreen|hair loss)\b", re.I)


def tier_for(*texts: str | None) -> str:
    """The most protective tier any of the texts (claim, notable, quote) hints at."""
    blob = " ".join(t for t in texts if t)
    if _CHILD.search(blob) and _CHILD_DETAIL.search(blob):
        return "children"
    if _LOCATION.search(blob):
        return "location"
    if _CLINICAL.search(blob):
        return "clinical"
    if _LIFESTYLE.search(blob):
        return "lifestyle"
    return "none"
