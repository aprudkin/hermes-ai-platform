# Deepgram voice source snapshot (dormant)

This directory versions the installed plugin and its local pitch-preserving
FFmpeg tempo wrapper. It is **not** an installation directory, and checking out
or testing this tree does not install, enable, discover, restart, or configure a
plugin. Do not add it to the live plugin search path as part of validation.

See [PROVENANCE.md](PROVENANCE.md), the unchanged upstream [MIT notice](LICENSE),
and [upstream README](UPSTREAM_README.md) for origin, credits, and provider details.
Upstream's installation/restart instructions are historical reference, not an
operation performed or required by this repository.

## Dependencies and compatibility

- Python >=3.11, `requests>=2.32.5,<3` (declared in `pyproject.toml`).
- A compatible Hermes installation or checkout exposing
  `agent.tts_provider.TTSProvider`, `agent.transcription_provider.TranscriptionProvider`,
  and `hermes_cli.config`. Hermes itself is not vendored here.
- Tempo processing requires `ffmpeg` with the `atempo` filter and `libopus`.
- Tests require pytest, Hermes config import dependencies (PyYAML and
  python-dotenv for the checked runtime), plus ffmpeg and ffprobe. A newer Hermes
  checkout may additionally require its own declared config-module dependencies.

The provider source and its Aura defaults are unchanged. Arbitrary voice/model
strings and independent STT/TTS base URLs remain supported. For Nova Russian,
explicitly select `stt.deepgram.model=nova-3`, `stt.deepgram.language=ru`,
`stt.deepgram.detect_language=false`, and the `/v1` base URL. For Flux Vladimir,
select `tts.deepgram.voice=flux-vladimir-ru` and
`tts.deepgram.base_url=https://api.deepgram.com/v2`; it calls `/v2/speak`.
These are explanatory options, **not** an exported or applied live config.
No persisted speed is assumed or changed. Credential values are never included.

## Tempo wrapper

`deepgram_tempo.py` uses its sibling plugin package. If Hermes is not already
importable, explicitly set `HERMES_SRC` to a compatible checkout (or provide it on
`PYTHONPATH`). The caller selects `HERMES_HOME`; the wrapper never invents one.
The CLI requires all of `--input`, `--output`, `--speed`, and `--voice`; there are
no personal voice/speed/profile defaults. Credentials are resolved by the plugin
through Hermes, not embedded in command arguments.

For speeds below 0.5 it synthesizes at native 0.5, then uses FFmpeg `atempo` with
`requested/native` to preserve pitch. Other speeds are forwarded unchanged and
post-processed with factor 1. Output remains Ogg/Opus. Invalid nonfinite or
nonpositive speeds are rejected before invoking a provider. The original
single-filter limitation remains: requested speeds below 0.25 exceed FFmpeg's
minimum atempo factor; no new multi-filter rate support is claimed. Failures
propagate; temporary source audio is cleaned up.

Calling the wrapper normally **does make a paid speech request**. The offline
suite instead injects a generated-tone provider and blocks Python network calls.
Its tone/duration/pitch checks are not evidence of a successful live API call or
human listening review.

## Offline verification

From the repository root, using an isolated Python environment with the above
dependencies already installed:

```bash
HERMES_SRC=/path/to/hermes PYTHON=/path/to/test-venv/bin/python \
  bash tests/deepgram_voice_test.sh -q
```

Alternatively, with uv and cached dependencies (no downloads):

```bash
HERMES_SRC=/path/to/hermes uv run --offline --no-project --python python3 \
  --with pytest --with 'requests>=2.32.5,<3' --with pyyaml --with python-dotenv \
  bash tests/deepgram_voice_test.sh -q
```

Dependency provisioning is separate from test execution; an empty uv cache must
be populated deliberately beforehand, or use a pre-provisioned test environment.
The runner fails rather than silently skipping missing Python/FFmpeg dependencies.
It uses a temporary HOME/HERMES_HOME, unsets Deepgram credentials/endpoint overrides,
disables bytecode/cache writes, and overrides upstream coverage-only pytest flags.
Tests mock HTTP and assert Russian Nova `/v1/listen` and Flux `/v2/speak` request
construction, exercise registration/config/error behavior, and process generated
440 Hz audio at several rates through real FFmpeg. No audio fixtures are stored.

`uv.lock`, `pyproject.toml`, the plugin manifest, and the upstream contract-install
helper are retained for provenance/development. The offline runner does not use
that helper, install an entry point, or mutate any runtime environment. No nested
Git metadata, catalog state, environments, private settings, identity, caches, or
upstream GitHub workflows are included.
