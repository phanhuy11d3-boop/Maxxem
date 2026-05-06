import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT_DIR / "tests" / "data" / "golden_dataset.json"
VALID_MARKET_IMPACTS = {"bullish", "bearish", "neutral"}


def load_dataset():
    with DATASET_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_golden_dataset_file_exists():
    assert DATASET_PATH.exists(), "Missing tests/data/golden_dataset.json"


def test_golden_dataset_has_valid_top_level_shape():
    data = load_dataset()
    assert isinstance(data, list), "Golden dataset must be a list"
    assert len(data) > 0, "Golden dataset must not be empty"


def test_golden_dataset_required_fields_and_types():
    data = load_dataset()
    seen_ids = set()

    for item in data:
        assert isinstance(item, dict), "Each dataset row must be an object"
        assert isinstance(item.get("id"), str) and item["id"].strip(), "Missing id"
        assert item["id"] not in seen_ids, f"Duplicate id found: {item['id']}"
        seen_ids.add(item["id"])

        assert isinstance(item.get("title"), str) and item["title"].strip(), f"Missing title in {item['id']}"
        assert isinstance(item.get("summary"), str) and item["summary"].strip(), f"Missing summary in {item['id']}"

        expected = item.get("expected")
        assert isinstance(expected, dict), f"Missing expected object in {item['id']}"

        sentiment = expected.get("sentiment")
        assert isinstance(sentiment, (int, float)), f"sentiment must be numeric in {item['id']}"
        assert -1.0 <= float(sentiment) <= 1.0, f"sentiment out of range in {item['id']}"

        market_impact = expected.get("market_impact")
        assert isinstance(market_impact, str), f"market_impact must be string in {item['id']}"
        assert market_impact in VALID_MARKET_IMPACTS, (
            f"market_impact must be one of {sorted(VALID_MARKET_IMPACTS)} in {item['id']}"
        )

        takeaway = expected.get("key_takeaway")
        assert isinstance(takeaway, str) and takeaway.strip(), f"Missing key_takeaway in {item['id']}"
