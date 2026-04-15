from src.collector.categories import classify_market


def test_geopolitical_classification():
    assert classify_market("Will Russia invade Finland by 2025?", None) == "geopolitical"
    assert classify_market("Will China blockade Taiwan?", None) == "geopolitical"
    assert classify_market("Will NATO deploy troops to Ukraine?", None) == "geopolitical"
    assert classify_market("Will Iran strike Israel before June?", None) == "geopolitical"


def test_political_classification():
    assert classify_market("Will Congress pass the TikTok ban?", None) == "political"
    assert classify_market("Will Biden sign the infrastructure bill?", None) == "political"
    assert classify_market("Will the Senate confirm the nominee?", None) == "political"
    assert classify_market("Will there be a government shutdown?", None) == "political"


def test_culture_classification():
    assert classify_market("Will Taylor Swift announce retirement?", None) == "culture"
    assert classify_market("Who will win Best Picture at the Oscars?", None) == "culture"
    assert classify_market("Will the Super Bowl halftime show feature Drake?", None) == "culture"
    assert classify_market("Will Elon Musk appear on SNL again?", None) == "culture"


def test_category_from_api_tag():
    assert classify_market("Some unclear question", "Politics") == "political"
    assert classify_market("Some unclear question", "Pop Culture") == "culture"
    assert classify_market("Some unclear question", "Geopolitics") == "geopolitical"


def test_other_fallback():
    assert classify_market("Will Bitcoin hit $100k?", None) == "other"
    assert classify_market("What will the weather be?", None) == "other"


def test_case_insensitive():
    assert classify_market("WILL NATO EXPAND?", None) == "geopolitical"
    assert classify_market("will congress act?", None) == "political"
