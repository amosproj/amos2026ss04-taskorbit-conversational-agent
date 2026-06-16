# Interchangeable STT/TTS Providers

> **Scope.** This guide explains how to choose the speech-to-text and
> text-to-speech provider per agent (ticket #135). Selection happens in
> the Agent Config UI; no code or environment change is needed to switch.
>
> The dispatch logic lives in
> `backend/src/taskorbit/livekit_agent/session.py` (`_build_stt` /
> `_build_tts`).

---

## What this is

Before #135 the voice pipeline was hardwired: Deepgram for STT, ElevenLabs
for TTS, both configured purely from environment variables. The provider
dropdowns in the Agent Config UI existed but had a single option, and the
values were discarded on the way to the voice worker.

Now both vendors are dual-capability and every combination works:

| | TTS: ElevenLabs | TTS: Deepgram (Aura) |
|---|---|---|
| **STT: Deepgram** | historical default | works |
| **STT: ElevenLabs (Scribe)** | works | works |

The selection travels: Agent Config UI -> saved agent -> LiveKit token
metadata -> voice worker -> plugin construction. Changing providers is a
dropdown choice, saved with the agent (AC4: no manual pipeline edits).

## Selecting providers in the UI

Pipeline section of the Agent Config page:

- **STT provider**: Deepgram or ElevenLabs. Switching resets the model to
  the provider default (same mismatch guard as the LLM section, #99).
- **TTS provider**: ElevenLabs or Deepgram. Same reset rule.
- **Voice ID** is only shown for ElevenLabs TTS. Deepgram Aura encodes the
  voice in the model name (`aura-2-<voice>-en`), so there is no separate
  voice field for it.

## Models and defaults

| Stage | Provider | Default model | Notes |
|---|---|---|---|
| STT | Deepgram | `nova-3` | any Deepgram STT model string works |
| STT | ElevenLabs | `scribe_v2_realtime` | **pinned**: the only Scribe model that streams. Batch models (`scribe_v1`, `scribe_v2`) return finals too late for the worker's turn handling, so the backend rejects them and falls back to the realtime model with a warning |
| TTS | ElevenLabs | `eleven_multilingual_v2` | any `eleven_*` model string works |
| TTS | Deepgram | `aura-2-andromeda-en` | voice is part of the model name |

Model fields are free text. A model name that clearly belongs to the other
provider is replaced with the selected provider's default at session build
time (warning logged). A wrong model within the correct provider's
namespace (for example a typo like `eleven_bogus`) fails at the provider
API during the call; check the worker logs.

## Precedence rules

For a normal call (agent config present in the room metadata) the agent
config wins over the environment:

- `tts.voice_id` from the config overrides `ELEVENLABS_VOICE_ID`.
  Before #135 env always won, which made the config field a
  non-functional placeholder.
- `stt.model` and `tts.model` from the config override `DEEPGRAM_MODEL`
  and `ELEVENLABS_MODEL`.

The environment values remain the fallback when no agent config reaches
the worker (no metadata, parse failure, or participant timeout) and when
config fields are empty.

## API keys

Both capabilities of a vendor share one key; nothing new is needed:

- `DEEPGRAM_API_KEY` covers Deepgram STT and TTS.
- `ELEVENLABS_API_KEY` covers ElevenLabs TTS and STT.

Selecting a provider whose key is missing fails the session at startup,
so keep both keys populated in any environment where users can switch.

## Observability

Every session logs its resolved selection at build time:

```
stt_selected  provider=elevenlabs model=scribe_v2_realtime
tts_selected  provider=elevenlabs model=eleven_multilingual_v2 voice_id=... voice_source=config
```

`voice_source` tells you whether the voice came from the agent config or
the env fallback. When a configured model does not belong to the selected
provider it is replaced with that provider's default and a single
`model_not_valid_for_provider` warning is logged (the `stage` field marks
it as `stt` or `tts`). Metadata problems are triaged: absent metadata logs info,
invalid metadata logs error (the user's selection is being overridden by
defaults), timeout/malformed JSON logs warning.

## Known limitations

- **Mid-call agent handoff does not re-apply providers.** The pipeline is
  built once per session from the initially dispatched agent; after an
  `agent_transfer` the original agent's STT/TTS (and voice) persist. This
  extends the known Sprint 8 voice hot-swap limitation.
- **The text-path TTS route** (`POST /v1/tts/synthesize`, used by typed
  chat playback) is ElevenLabs-only and is not governed by this
  selection. Out of scope for #135, which covers the voice pipeline.
- **`stt.language` is not yet wired**; the Deepgram language comes from
  `DEEPGRAM_LANGUAGE` and ElevenLabs Scribe auto-detects.
- The **System Architecture document** (`Documentation/Taskorbit
  Conversational Agent System Architecture - final.*` and the Runtime
  Components diagram) depicts the historical fixed pipeline (Deepgram
  STT -> ElevenLabs TTS). Read that as the default configuration; the
  stages are provider-selectable as of #135.
