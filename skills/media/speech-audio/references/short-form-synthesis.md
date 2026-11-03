# Short-form speech synthesis fallback

Use only after the configured speech path fails and the text is suitable for this external service. This method has successfully generated short Russian voice messages. Service availability, quotas and response shape can change; verify each response rather than assuming continued support. It does not establish a persistent Hermes provider configuration.

## Minimal method

1. Keep each external request below 200 characters. Use one request for each short logical voice message. For longer messages, split at natural boundaries and retain a mapping from chunks to logical messages; only chunks of the same message may be joined.
2. Build the HTTPS request with Python stdlib urllib.parse.urlencode and urllib.request:
   - Origin/path: `https://translate.google.com/translate_tts`
   - Query: `ie=UTF-8`, `client=tw-ob`, `tl=ru`, `q=<exact text>`.
   - Header: `User-Agent: Mozilla/5.0`.
   - Use a bounded timeout, such as 25 seconds.
   Do not put text containing credentials or private information into this URL. Do not log the complete query for sensitive text.
3. Require a successful response with Content-Type beginning `audio/` and nontrivial bytes before saving an MP3 in a private task directory. Never save an HTML error page with an audio extension and call it a recording. Use an explicit file path per logical message; do not overwrite earlier requested messages.
4. Convert each message independently through subprocess argv, with actual discovered executable paths:
   ```text
   ffmpeg -nostdin -y -i INPUT.mp3 -c:a libopus -b:a 48k OUTPUT.ogg
   ffprobe -v error -show_entries format=duration,size -of json OUTPUT.ogg
   ```
   Inspect real exit codes and require positive duration and size. ffmpeg is a runtime prerequisite, not something this recipe silently installs.
5. Deliver each separate result as:
   ```text
   [[audio_as_voice]]
   MEDIA:/absolute/path/to/OUTPUT.ogg
   ```

If an earlier attempt concatenated several already-generated MP3 parts but the user wants separate notes, convert the saved original parts separately; do not resynthesize or send the combined file again. If the external request fails, preserve the failure and try another authorized available method or report the blocker; do not describe the failed route as a successful recording.
