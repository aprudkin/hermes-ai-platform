"""Profile-local Deepgram TTS with pitch-preserving sub-minimum tempo."""
import argparse
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def synthesize(text, output_path, *, speed, voice, provider=None):
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError('speed must be a finite positive number')
    if provider is None:
        root = Path(__file__).resolve().parent
        source = os.environ.get('HERMES_SRC')
        sys.path[:0] = [str(root)] + ([source] if source else [])
        from hermes_deepgram_voice.tts import DeepgramTTSProvider
        provider = DeepgramTTSProvider()
    native_speed = 0.5 if speed < 0.5 else speed
    factor = speed / native_speed
    with tempfile.TemporaryDirectory(prefix='deepgram-tempo-') as tmp:
        source = str(Path(tmp) / 'native.ogg')
        provider.synthesize(text, source, voice=voice, speed=native_speed, format='ogg')
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', source,
            '-filter:a', f'atempo={factor:.12g}', '-c:a', 'libopus',
            '-f', 'ogg', str(output_path),
        ], check=True, timeout=120)
    return str(output_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--speed', type=float, required=True)
    parser.add_argument('--voice', required=True)
    args = parser.parse_args()
    synthesize(Path(args.input).read_text(encoding='utf-8'), args.output,
               speed=args.speed, voice=args.voice)
