import re

# API tag label -> our category
# Note: Order matters - check longer/more specific patterns first
TAG_MAP: dict[str, str] = {
    "geopolitics": "geopolitical",
    "us politics": "political",
    "politics": "political",
    "elections": "political",
    "world": "geopolitical",
    "pop culture": "culture",
    "entertainment": "culture",
    "sports": "culture",
    "celebrities": "culture",
}

# Keyword patterns for classification from question text
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "geopolitical": [
        r"\b(invade|invasion|blockade|nato|troops|missile|nuclear|sanctions|annex)\b",
        r"\b(russia|china|iran|ukraine|taiwan|israel|north korea|syria)\b",
        r"\b(war|conflict|military|airstrike|deploy|ceasefire|treaty)\b",
    ],
    "political": [
        r"\b(congress|senate|house|parliament|legislation|bill|law|act)\b",
        r"\b(president|governor|mayor|election|vote|ballot|impeach)\b",
        r"\b(government shutdown|executive order|veto|filibuster|confirm)\b",
        r"\b(biden|trump|democrat|republican|gop)\b",
    ],
    "culture": [
        r"\b(oscar|grammy|emmy|tony|golden globe|award show|best picture)\b",
        r"\b(super bowl|world series|nba|nfl|world cup|olympics)\b",
        r"\b(taylor swift|beyonce|drake|kanye|elon musk|celebrity)\b",
        r"\b(movie|album|tour|concert|halftime|snl|netflix|spotify)\b",
        r"\b(retire|comeback|announce|release|premiere)\b",
    ],
}


def classify_market(question: str, api_category: str | None) -> str:
    # First, try to classify from the API-provided category/tag
    if api_category:
        tag_lower = api_category.lower()
        # Sort by length (longest first) to match more specific patterns first
        for tag_key in sorted(TAG_MAP.keys(), key=len, reverse=True):
            if tag_key in tag_lower:
                return TAG_MAP[tag_key]

    # Fall back to keyword matching on the question text
    question_lower = question.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question_lower):
                return category

    return "other"
