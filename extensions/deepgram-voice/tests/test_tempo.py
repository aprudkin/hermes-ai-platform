from __future__ import annotations

import os
from pathlib import Path
import sys

import deepgram_tempo
import pytest


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_invalid_speed_rejected_before_synthesis(speed, tmp_path):
    class Provider:
        def synthesize(self, *args, **kwargs):
            pytest.fail("Invalid speed must not reach a speech provider")

    with pytest.raises(ValueError, match="finite positive"):
        deepgram_tempo.synthesize(
            "test", tmp_path / "out.ogg", speed=speed, voice="flux-vladimir-ru", provider=Provider()
        )


def test_default_provider_uses_explicit_source_without_changing_profile(monkeypatch, tmp_path):
    from hermes_deepgram_voice import tts

    calls = []

    class Provider:
        def synthesize(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(tts, "DeepgramTTSProvider", Provider)
    monkeypatch.setattr(deepgram_tempo.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("HERMES_SRC", str(tmp_path / "hermes-source"))
    output = tmp_path / "out.ogg"

    assert deepgram_tempo.synthesize("test", output, speed=0.4, voice="flux-vladimir-ru") == str(output)

    assert os.environ.get("HERMES_HOME") is None
    assert sys.path[:2] == [
        str(Path(deepgram_tempo.__file__).resolve().parent),
        str(tmp_path / "hermes-source"),
    ]
    assert calls[0][1] == {"voice": "flux-vladimir-ru", "speed": 0.5, "format": "ogg"}
