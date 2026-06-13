from sources.dexscreener_realtime_shadow import load_realtime_shadow_config


def test_realtime_shadow_disabled_by_default():
    cfg = load_realtime_shadow_config({})
    assert cfg.enabled is False
    assert cfg.safe is True


def test_realtime_shadow_detects_unsafe_side_effects():
    cfg = load_realtime_shadow_config({
        "sources": {
            "dexscreener_realtime": {
                "enabled": True,
                "provider": "apify",
                "write_signals": True,
            }
        }
    })
    assert cfg.enabled is True
    assert cfg.provider == "apify"
    assert cfg.safe is False

