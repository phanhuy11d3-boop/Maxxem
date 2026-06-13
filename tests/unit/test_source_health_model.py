from sources.base import SourceHealth


def test_source_health_defaults():
    health = SourceHealth(
        source="dexscreener_rest",
        chain_id="solana",
        stream_id="rest_batch",
        status="healthy",
        messages_seen=3,
    )
    assert health.source == "dexscreener_rest"
    assert health.messages_seen == 3
    assert health.updated_at.tzinfo is not None

