"""Real offline FFmpeg checks, not a simulated Deepgram API result."""
from __future__ import annotations

from array import array
import json
from pathlib import Path
import subprocess
import sys

import pytest

import deepgram_tempo


@pytest.mark.parametrize("speed", [0.25, 0.4, 0.5, 1.0, 1.4])
def test_generated_tone_preserves_pitch_and_requested_tempo(tmp_path, speed):
    calls = []

    class ToneProvider:
        def synthesize(self, text, output_path, **kwargs):
            calls.append((text, output_path, kwargs))
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=2",
                "-c:a", "libopus", "-f", "ogg", output_path,
            ], check=True, timeout=30)
            return output_path

    output = tmp_path / "tempo.ogg"
    assert deepgram_tempo.synthesize(
        "generated tone only", output, speed=speed, voice="flux-vladimir-ru", provider=ToneProvider()
    ) == str(output)

    _, source, options = calls[0]
    native_speed = max(0.5, speed)
    assert options == {"voice": "flux-vladimir-ru", "speed": native_speed, "format": "ogg"}
    assert not Path(source).exists()
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output),
    ], timeout=30))
    assert probe["streams"][0]["codec_name"] == "opus"
    assert probe["format"]["format_name"] == "ogg"
    assert abs(float(probe["format"]["duration"]) - 2 * native_speed / speed) < 0.15

    pcm = subprocess.check_output([
        "ffmpeg", "-v", "error", "-nostdin", "-i", str(output),
        "-f", "s16le", "-ac", "1", "-ar", "48000", "pipe:1",
    ], timeout=30)
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    # Ignore codec edges; count positive zero crossings in the middle.
    samples = samples[4800:-4800]
    crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
    frequency = crossings * 48000 / len(samples)
    assert abs(frequency - 440) < 3


def test_ffmpeg_failure_propagates_and_cleans_temporary_audio(monkeypatch, tmp_path):
    sources = []

    class Provider:
        def synthesize(self, text, output_path, **kwargs):
            sources.append(Path(output_path))
            sources[-1].write_bytes(b"not actual audio")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(deepgram_tempo.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        deepgram_tempo.synthesize(
            "test", tmp_path / "out.ogg", speed=0.4, voice="flux-vladimir-ru", provider=Provider()
        )
    assert not sources[0].exists()
