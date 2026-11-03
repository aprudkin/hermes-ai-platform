# Speech-rate adjustment

## Procedure

1. Resolve whether the user requests a one-off sample or a lasting default. During an ongoing rate-selection exchange, a bare decimal means the next default rate. Interpret a Russian decimal comma as a decimal separator, not a different voice or model. Preserve the existing voice, language, incoming STT and automatic-reply mode.
2. Read the active profile's TTS configuration and the provider's current rate limits. Use supported Hermes config setters; do not rewrite YAML by hand. Store a previous working setting before changing the route. A saved-key warning is not proof that runtime ignores a documented open-dictionary configuration field: verify actual synthesis.
3. If the rate is natively supported, set `tts.speed` and use the direct provider. If returning from a local tempo wrapper, restore the direct provider as well, so an obsolete processing layer does not remain active unnecessarily.
4. If the requested rate lies below the provider's minimum, state the boundary before choosing pitch-preserving post-processing. Do not silently clamp the request or claim native support. Use a supported native rate and a local tempo factor whose product is the requested rate; calculate the factor with a tool.
5. Call the normal `text_to_speech` tool with no explicit speed or provider override. An override would test that invocation instead of the saved default. Keep one short sample phrase constant across comparisons; varying the spoken rate label also varies syllable count and makes durations incomparable.
6. Verify nonempty, decodable audio and positive duration with ffprobe; confirm Ogg/Opus for a Telegram voice note. A successful parse proves an audio artifact, not perceived naturalness or exact effective speaking rate. Do not run ASR merely to recheck a tiny synthesis sample.
7. Deliver one sample with a minimal confirmation. If the user then approves sending it elsewhere, send the already-generated file rather than generating another potentially different take. Do not resend because a delayed completion notification repeats an already-confirmed send.

## Deepgram Flux Vladimir

- Distinguish Flux TTS from Flux STT. Russian Vladimir is `flux-vladimir-ru`; the language is selected by the model suffix.
- Use `POST https://api.deepgram.com/v2/speak`; Aura's `/v1/speak` does not serve Flux TTS voices. The catalog native plugin can use arbitrary voice strings with a provider-specific `/v2` base URL even if its displayed list contains only Aura voices.
- Configure `tts.provider=deepgram`, `tts.voice=flux-vladimir-ru`, `tts.deepgram.voice=flux-vladimir-ru`, `tts.deepgram.base_url=https://api.deepgram.com/v2`, and `tts.output_format=ogg` through supported setters. Reuse the existing profile credential; never include it in command arguments or examples.
- Deepgram documents native speed from 0.5 to 1.5 in 0.05 increments. Check current docs and the requested voice rather than making a blanket language-support claim: documentation qualifies control support, while actual Russian Vladimir requests at 0.5, 0.6, 0.7 and 0.85 produced audio successfully.
- The standard config setter may warn about `tts.speed`; direct synthesis verified that it is consumed. Use `hermes config set tts.speed <rate> --force` for this known supported field, then test the default route.

## Pitch-preserving tempo below the API minimum

For a requested rate of 0.4, the verified method is native synthesis at 0.5 followed by FFmpeg `atempo=0.8`. This preserves pitch while changing tempo; it is not native provider support for 0.4. Do not describe algorithmic pitch preservation as an audited guarantee of perceptual voice quality.

One-off processing:

```bash
ffmpeg -v error -nostdin -y -i native.ogg -filter:a atempo=0.8 -c:a libopus -f ogg slower.ogg
```

For persistence, use a profile-local supported command provider rather than patching Hermes core or the vendor plugin. The verified manager helper is `$HERMES_HOME/scripts/deepgram_tempo.py`, exposed as `tts.providers.deepgram-tempo`. Verify the helper exists before selecting it. Its command receives `{input_path}`, `{output_path}`, `{speed}` and `{voice}`, calls the original Deepgram provider, and applies local FFmpeg tempo adjustment. Configure its output format as Ogg, voice compatibility explicitly true, and a bounded timeout. Keep the direct Deepgram provider settings intact for reuse.

Test any new wrapper before activation with a local synthetic tone and an injected provider: assert the cloud speed stays within supported bounds, the voice argument is preserved, and actual FFmpeg output duration reflects the residual factor. Then exercise a real synthesis through the default tool. When moving back into the native range, select `tts.provider=deepgram` and leave the unused wrapper inactive.

Sources to recheck when behavior changes:
- https://developers.deepgram.com/docs/tts-voice-controls
- https://developers.deepgram.com/docs/flux-tts/voices
- https://developers.deepgram.com/docs/flux-tts/quickstart
- https://hermes-agent.nousresearch.com/docs/plugins/deepgram-voice
