# Provenance and local adaptation

## Plugin

- Upstream: <https://github.com/jaysonsantos/hermes-deepgram-voice-plugin>
- Installed revision: `2d31b885ec873ed6693edd7ad1a80f7023439ac0`
- Upstream version: `0.1.0`
- Revision subject: `fix: require Python >=3.11 and fix Hermes CI install (#10)`
- Imported from the actual installed Git worktree, not downloaded afresh. All
  tracked installed files matched HEAD at capture time; the sole untracked
  `.hermes-catalog.json` was installer metadata and was excluded.
- `LICENSE` is the original MIT license, including the 2026 Jayson Santos dos
  Reis copyright. The full original README and its prior-work credits are
  preserved byte-for-byte as `UPSTREAM_README.md`.
- Provider package, directory entry point, manifest, pyproject, lockfile,
  contract-install helper, and original test files were copied from disk.
  Provider/package/manifest/dependency sources remain byte-identical. The only
  modified upstream test file is `tests/conftest.py`, which adds an autouse
  network-denial fixture. Other local tests are additions.
- Omitted upstream artifacts: `.github/` workflows/Dependabot,
  `.pre-commit-config.yaml`, and `after-install.md`. They are unnecessary for
  dormant preservation and this repository's test runner. No nested `.git`,
  ignored caches, environments, or generated artifacts were copied.

## Local tempo wrapper

- `deepgram_tempo.py` came from the operator's installed profile script, not the
  upstream plugin repository. Its original SHA-256 was
  `421719ebaab90cd3e01e057efd1492e85a3d554cc253854931e9693cf376fee4`.
- Local changes: find the sibling package within this extension; accept an
  explicit `HERMES_SRC` checkout instead of a hardcoded runtime path; leave
  `HERMES_HOME` entirely to the caller; reject nonpositive/nonfinite speed before
  provider invocation. Voice and speed remain required, with no personal defaults.
- Native speed selection, voice forwarding, Ogg/Opus output, checked FFmpeg
  invocation, timeout, temporary-file cleanup, and CLI arguments are retained.
- The installed wrapper had no separate copyright/license notice. Its provenance
  is local operator-provided code; do not attribute its authorship or a separate
  license grant to the upstream MIT author. The original upstream notice remains
  intact for the upstream plugin material.

## Verification boundary

Only source/test files were added to the maintenance repository. No install,
entry-point activation, plugin discovery, config edits, service restarts, or
speech API calls were performed. A temporary profile and generated-tone audio
were used for offline tests. Test speeds are examples, not a claim about the
current persisted live speed. The plugin's Aura defaults were not changed into
personalized defaults; Russian Nova and Flux behavior is covered by offline
request-construction regressions.
