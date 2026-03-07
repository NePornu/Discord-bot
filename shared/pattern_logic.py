"""
Shared logic for pattern detection: keywords, normalization, and word counting.
Used by both the PatternDetectorCog and standalone backfill scripts.
"""

import re
from typing import Dict, List

# ─── Keyword Groups (Czech) ──────────────────────────────────────────

KEYWORD_GROUPS = {
    "relapse_fatigue": ["znovu", "zase", "bohužel", "selhal", "znov"],
    "euphoria": ["super", "zvládnu", "dokonalé", "pod kontrolou", "mám to",
                 "úžasné", "skvělé", "perfektní", "zvládám"],
    "restart_lang": ["chtěl bych", "zase začal", "dní bez", "začínám",
                     "restart", "od začátku", "nový pokus"],
    "wall_keywords": ["nevím", "stále", "pořád stejné", "dokola",
                      "stále stejné", "netuším"],
    "absolutisms": ["všechno", "nikdy", "vždy", "nic", "úplně",
                    "absolutně", "totálně"],
    "activation": ["už nemůžu", "včera se to stalo", "poprvé píšu",
                   "první příspěvek", "jsem tu nový", "rozhodl jsem se"],
    "relapse_word": ["relaps", "relapsnul", "selhal jsem"],
    "apology_return": ["omlouvám se", "dlouho jsem tu nebyl", "vracím se",
                       "jsem zpět", "chyběl jsem"],
    "methodology": ["deník", "parťák", "metodika", "denní rutina",
                    "studená sprcha", "meditace", "cvičení"],
    "help_others": ["vítám", "vítej", "držím palce", "drž se",
                    "ahoj", "rád tě vidím", "neboj se"],
    "despair": ["nemá to cenu", "vzdávám", "končím", "sbohem",
                "odcházím", "konec"],
}

# Match whole words for short keywords to avoid false positives
SHORT_WORDS = {"nic", "vždy", "stále", "zase", "znovu", "super", "ahoj"}


def normalize_text(text: str) -> str:
    """Normalize for keyword matching — lowercase, strip extra whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower().strip())


def count_keywords(text: str, group: str) -> int:
    """Count keyword hits for a group in text."""
    norm = normalize_text(text)
    if not norm:
        return 0
    count = 0
    for kw in KEYWORD_GROUPS.get(group, []):
        if len(kw) <= 4 or kw in SHORT_WORDS:
            # Whole-word match for short words
            count += len(re.findall(rf"\b{re.escape(kw)}\b", norm))
        else:
            count += norm.count(kw)
    return count


def count_words(text: str) -> int:
    """Count words in text."""
    if not text:
        return 0
    return len(text.split())

def get_keyword_hits(text: str) -> Dict[str, int]:
    """Get hits for all keyword groups."""
    hits = {}
    for group in KEYWORD_GROUPS:
        count = count_keywords(text, group)
        if count > 0:
            hits[group] = count
    return hits
