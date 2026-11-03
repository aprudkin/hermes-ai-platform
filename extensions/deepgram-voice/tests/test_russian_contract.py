"""Preserve configured Russian Nova/Flux request behavior without network I/O."""
from __future__ import annotations

from hermes_deepgram_voice import stt, tts


def test_nova_russian_config_keeps_v1_endpoint(monkeypatch, tmp_path, fake_response):
    calls = {}
    audio = tmp_path / "synthetic.ogg"
    audio.write_bytes(b"offline fixture, not recorded speech")
    monkeypatch.setattr(stt, "get_env", lambda name, default="": "test-only-not-a-key")
    monkeypatch.setattr(stt, "provider_config", lambda section: {
        "model": "nova-3", "language": "ru", "detect_language": False,
        "base_url": "https://api.deepgram.com/v1", "timeout": 120,
    })
    monkeypatch.setattr(stt, "post", lambda **kwargs: calls.update(kwargs) or fake_response)
    fake_response.payload = {"results": {"channels": [{"alternatives": [{"transcript": "fixture"}]}]}}

    result = stt.DeepgramSTTProvider().transcribe(str(audio))

    assert result["success"]
    assert calls["url"] == "https://api.deepgram.com/v1/listen"
    assert calls["params"]["model"] == "nova-3"
    assert calls["params"]["language"] == "ru"
    assert "detect_language" not in calls["params"]


def test_flux_vladimir_config_uses_v2_speak(monkeypatch, tmp_path, fake_response):
    calls = {}
    monkeypatch.setattr(tts, "get_env", lambda name, default="": "test-only-not-a-key")
    monkeypatch.setattr(tts, "provider_config", lambda section: {
        "voice": "flux-vladimir-ru", "base_url": "https://api.deepgram.com/v2", "timeout": 120,
    })
    monkeypatch.setattr(tts, "post", lambda **kwargs: calls.update(kwargs) or fake_response)

    tts.DeepgramTTSProvider().synthesize("offline fixture", str(tmp_path / "out.ogg"),
                                      speed=0.5, format="ogg")

    assert calls["url"] == "https://api.deepgram.com/v2/speak"
    assert calls["params"] == {"model": "flux-vladimir-ru", "encoding": "opus",
                               "container": "ogg", "speed": 0.5}
    assert calls["timeout"] == 120
