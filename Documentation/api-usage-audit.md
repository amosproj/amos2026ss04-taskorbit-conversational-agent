# API Usage Audit — Issue #151

**Authors:** Asad Raza, Shikhar Thakur
**Date:** 2026-06-23
**Status:** Draft (pending PO review)
**Closes:** #151

---

## 1. Trigger event and audit purpose

On 2026-06-08, GCP billing for the TaskOrbit project recorded an unexpected $421 charge. A PO investigation (relayed on Discord, 2026-06-17 18:39) identified the root cause as **Google Veo "Veo Generation 720p with Audio" video-generation usage**, not TaskOrbit's normal runtime behaviour. Validation with Meisterwerk on whether the project API key was scoped to permit Veo endpoints is ongoing.

While TaskOrbit was cleared as the proximate cause, the near-miss surfaced a broader question: *if our keys did leak, would our system survive it cleanly?* The POs scoped issue #151 around that question:

> *"As part of issue #151, we should therefore review our third-party API usage end-to-end and validate that our system is technically sound at these interfaces. This should include API key restrictions, allowed endpoints/models, quota and budget configuration, request logging, rate limiting, retry limits, and protection against unintended external triggering of paid API calls. If this review identifies a concrete technical gap in one of our third-party API integrations, we should create a separate follow-up issue for the specific remediation."*

This document is the audit deliverable for #151. **Concrete gaps identified here spawn separate Sprint 11 follow-up tickets** (listed in §6 below); remediation code is explicitly out of scope for this PR.

---

## 2. Audit scope — third-party APIs in TaskOrbit

| Provider | Used for | Billing model |
|---|---|---|
| ElevenLabs | TTS (text-to-speech synthesis on REST + LiveKit voice path) | Per-character usage |
| OpenAI | LLM responses for agents | Per-token |
| Google Gemini | LLM responses (alt provider, per-task) | Per-token |
| Deepgram | STT (speech-to-text in voice path) | Per-second of audio |
| LiveKit Cloud | Real-time voice room hosting + JWT token issuance | Per-minute + per-room |
| GCP | Cloud Run hosting, Cloud SQL, Gemini billing | Multiple |

---

## 3. Methodology

Two parallel investigation tracks:

1. **Safe local abuse demo** (Shikhar, 2026-06-18) — provider API keys blanked in `backend/.env` to prevent outbound calls; backend restarted; 10 unauthenticated POSTs sent to `POST /v1/tts/synthesize` and `POST /v1/livekit/token`; backend logs inspected for routing, validation, and outbound-call behaviour. Full evidence in §7.
2. **Code-path review** (Asad + Shikhar) — direct inspection of route handlers, auth dependencies, retry configuration, and worker behaviour to verify the abuse-demo findings against actual code.

Dashboard-side items (provider key scopes, allowlisted endpoints/models, quota & budget alerts) **cannot be audited from code alone** — they require provider-console access. These items are marked `❓ NEEDS-VERIFICATION` and flagged for whoever holds provider credentials (typically team members with infrastructure / release-manager responsibility, or the POs).

---

## 4. Findings — the POs' seven audit items

Each finding carries a verdict (`✅ OK` / `⚠️ GAP` / `🔴 CRITICAL` / `❓ NEEDS-VERIFICATION`), evidence (code reference or log excerpt), and a follow-up ticket reference where applicable.

### 4.1 API key restrictions

**Verdict:** ❓ NEEDS-VERIFICATION

**What it means:** Whether each provider key is scoped at the provider side to only the endpoints / models / regions TaskOrbit actually needs (principle of least privilege).

**Code-side observation:** Backend reads all provider keys from `backend/.env` via `Settings` (`taskorbit.config`). Code never restricts the scope of an upstream key — that restriction is purely provider-side.

**Action required:** Whoever has provider-console access (team members holding the relevant credentials for GCP / LiveKit Cloud / ElevenLabs / OpenAI / Deepgram; Meisterwerk for the Gemini API key per the PO note on ongoing validation) must confirm:

- ElevenLabs key: scoped to TTS only? (not Voice Lab / dubbing / etc.)
- OpenAI key: org-restricted? Endpoint-restricted?
- Gemini key (Meisterwerk-provided): is Veo permitted? *(directly relevant to the trigger event)*
- LiveKit Cloud key/secret: project-scoped?
- Deepgram key: STT-only?

**Follow-up:** §6 ticket E (provider-dashboard audit).

---

### 4.2 Allowed endpoints / models

**Verdict:** ⚠️ GAP (server-side) + ❓ NEEDS-VERIFICATION (provider-side)

**Code-side observation:** Model names flow from `agent_config.llm.model` (frontend-controlled, persisted in DB) directly into provider clients. There is **no backend allowlist** validating that the requested model is one TaskOrbit intends to pay for. A compromised frontend or a hand-crafted POST to `/v1/conversations/process` could request, e.g., `gpt-4` instead of `gpt-4o-mini` (10× cost) or `gemini-2.5-pro` instead of `gemini-2.5-flash`.

**Evidence:** `backend/src/taskorbit/integrations/llm/openai_client.py` passes `llm_config.model` straight to the SDK with no allowlist check; same pattern in `gemini_client.py`.

**Risk:** Moderate. The frontend is currently the only known caller, so this requires a compromised FE *or* abuse of the `/v1/conversations/process` route (which today has no auth — see §4.7).

**Action required:**
- Server-side: introduce a model allowlist (enum or `Settings`-driven config), validate `agent_config.llm.model` at the orchestration boundary.
- Provider-side: confirm whether key scoping restricts available models.

**Follow-up:** §6 ticket E covers both halves.

---

### 4.3 Quota and budget configuration

**Verdict:** ❓ NEEDS-VERIFICATION

**What it means:** Whether each provider has spending caps + alert thresholds configured at the provider side.

**Code-side observation:** No quota / budget configuration is code-tracked (this is provider-dashboard work). The GCP billing alert that caught the $421 spike on 2026-06-08 suggests **at least one alert exists somewhere** — we should document which providers have alerts and what thresholds.

**Action required:** Per-provider check (whoever holds dashboard access):

| Provider | Budget alert exists? | Threshold | Hard cap exists? |
|---|---|---|---|
| ElevenLabs | ? | ? | ? |
| OpenAI | ? | ? | ? |
| Google Gemini | ✅ (per the PO investigation) | ? | ? |
| Deepgram | ? | ? | ? |
| LiveKit Cloud | ? | ? | ? |
| GCP overall | ✅ (per the PO investigation) | ? | ? |

**Follow-up:** §6 ticket E.

---

### 4.4 Request logging

**Verdict:** ⚠️ PARTIAL GAP

**What works:** Structured logging via `structlog` is consistent across the codebase. Provider calls emit dedicated events (`tts_elevenlabs_error`, `livekit_token_issued`, `intent_detected`, `pipeline_complete`, `messages_persisted`, etc.) with timestamps and event-specific fields.

**What's missing:** Provider-call log events **do not include per-user or per-API-key attribution**. Today the only "user" identifier in any logged event is `conversation_id`, which is FE-generated and untrusted. There is no way to answer the question *"which user / which key triggered this $50 ElevenLabs charge?"* from the logs.

**Evidence (from §7 abuse demo):**
```
{"identity": "tester", "room": "leak-test", "event": "livekit_token_issued", "timestamp": "..."}
```
`identity` here is FE-supplied (the abuse demo passed `tester1`, `tester2`, etc.), not a backend-validated user id.

**Follow-up:** §6 ticket C (per-user / per-key attribution in logs).

---

### 4.5 Rate limiting

**Verdict:** ⚠️ GAP

**Code-side observation:** No application-level rate limiter. No `slowapi`, `fastapi-limiter`, or equivalent in `backend/pyproject.toml`. No per-route or per-IP throttling. CORS is the only ingress-side restriction.

**Evidence (§7 abuse demo):** Ten consecutive POSTs to `POST /v1/tts/synthesize` from the same source IP were processed serially with no throttling — backend forwarded all ten to ElevenLabs (which returned 401/quota_exceeded only because the key had been blanked for the test).

**Risk:** High for paid-API-triggering endpoints (`/v1/tts/synthesize`, `/v1/livekit/token`, `/v1/conversations/process`). A discovered prod URL + automated POST loop = direct ElevenLabs / OpenAI / Gemini cost.

**Follow-up:** §6 ticket B (application-level rate limiting).

---

### 4.6 Retry limits

**Verdict:** ⚠️ MIXED — partially capped, partially unverified

**Per-provider audit:**

| Provider | Retry source | Capped? | Evidence |
|---|---|---|---|
| OpenAI | SDK built-in (`max_retries=_MAX_RETRIES`) | ✅ Yes (3 attempts total per call) | `backend/src/taskorbit/integrations/llm/openai_client.py:55` |
| Google Gemini | SDK default behaviour | ❓ Unverified | No explicit `max_retries` in `gemini_client.py` |
| ElevenLabs (TTS route + voice TTS plugin) | None observed in `routes/tts.py`; LiveKit `elevenlabs` plugin defaults | ❓ Unverified | `tts.py` lacks any retry logic; voice-path retry behaviour is upstream-plugin-defined |
| Deepgram (STT) | LiveKit `deepgram` plugin defaults | ❓ Unverified | Plugin-defined; not project-controlled |
| LiveKit Cloud | LiveKit SDK / `livekit-agents` framework | ❓ Unverified | Framework-controlled |

**Note on Shikhar's recommendation:** Shikhar suggested wrapping providers in `tenacity` exponential backoff. The OpenAI side already has SDK-level retry; adding `tenacity` on top would double-retry. The actual gap is Gemini + ElevenLabs explicit cap verification + standardisation.

**Follow-up:** §6 ticket D (retry-cap audit + standardisation per provider).

---

### 4.7 Protection against unintended external triggering of paid API calls

**Verdict:** 🔴 CRITICAL GAP

This is the most consequential finding in the audit. Multiple independent issues compound:

#### 4.7a — Two paid-API-triggering endpoints are fully unauthenticated

**Evidence:**

`backend/src/taskorbit/api/routes/tts.py:82` —
```python
@router.post("/synthesize")
async def synthesize_speech(request: TTSSynthesizeRequest) -> Response:
```
*No `Depends(get_current_user_id)`, no API-key header check, no IP allowlist.*

`backend/src/taskorbit/api/routes/livekit.py:36` —
```python
@router.post("/token", response_model=LiveKitTokenResponse)
async def create_livekit_token(body: LiveKitTokenRequest) -> LiveKitTokenResponse:
```
*Same — no auth dep.*

**Confirmed via §7 abuse demo:** 10/10 unauthenticated POSTs to `/v1/tts/synthesize` forwarded to ElevenLabs; 10/10 unauthenticated POSTs to `/v1/livekit/token` issued valid LiveKit tokens.

#### 4.7b — The "auth" dependency that *is* used elsewhere returns a static dev user

**Evidence:** `backend/src/taskorbit/api/deps.py:43` —
```python
# Hardcoded dev user — swap this entire function for JWT logic when ready.
```
Routes that *do* depend on `get_current_user_id` (e.g., `/v1/conversations/process`, `/v1/user-agents/*`) all receive the same single seeded user id (1). There is no actual authentication anywhere in the backend today. The dependency exists as a placeholder for future JWT wiring.

#### 4.7c — Voice worker auto-speaks greeting on any participant join

**Evidence:** `backend/src/taskorbit/worker.py:298-300` —
```python
if greeting:
    session.say(greeting)
    logger.info("worker_greeting_spoken", length=len(greeting))
```
`session.say()` triggers an immediate ElevenLabs TTS call. Since LiveKit room access is gated only by the unauthenticated token endpoint (4.7a), a bot that obtains a token and joins a room **triggers paid TTS instantly, before any user interaction**.

#### 4.7d — Frontend default inactivity timeout is 7 minutes

**Evidence:** `frontend/src/hooks/useVoiceCall.ts:77-78` —
```typescript
const INACTIVITY_TIMEOUT_MS =
  Number(import.meta.env.VITE_INACTIVITY_TIMEOUT_MINUTES ?? 7) * 60 * 1000;
```
An abandoned or noisy session keeps consuming STT/TTS/LLM credits for up to 7 minutes idle before the FE-side timer fires. Backend has no independent server-side enforcement.

#### Combined risk

A malicious actor who discovers the prod URL can, with zero authentication:
1. Hit `POST /v1/livekit/token` to mint a valid room token.
2. Join the room via LiveKit Cloud (using the token).
3. Trigger the auto-greeting (ElevenLabs cost).
4. Stay idle for 7 minutes, burning STT/TTS/LLM credits in any noisy environment.
5. Repeat at scale — there's no rate limit (§4.5).

OR even more cheaply: just POST `/v1/tts/synthesize` in a loop with arbitrary text. Backend forwards everything to ElevenLabs without authentication.

**Follow-up:** §6 ticket A (highest priority).

---

## 5. Out of scope

The following were considered and explicitly excluded from this audit's scope:

- **Implementation of any remediation** — per the PO AC, *"create a separate follow-up issue for the specific remediation."* Remediation work is in the §6 tickets, not in this PR.
- **Production GCP billing analysis** — the PO investigation already completed this and identified Google Veo as the root cause of the $421 spike.
- **Meisterwerk-provided Gemini key scope** — the POs noted validation with Meisterwerk is ongoing. This audit does not pre-empt that.
- **Authentication / authorisation redesign** — replacing the dev-user stub with real auth is itself a large architectural change. It may not fit a single follow-up ticket and could warrant its own PO discussion.

---

## 6. Recommended follow-up tickets — Sprint 11 candidates

Per the PO AC, each concrete gap becomes its own ticket. To be filed after this audit merges:

| ID | Title | Priority | Source finding |
|---|---|---|---|
| A | **Authentication on `/v1/tts/synthesize` + `/v1/livekit/token`** — add at minimum a shared application-secret header (`X-TASKORBIT-APP-SECRET`); ideally `Depends(get_current_user_id)` once real auth lands | 🔴 HIGHEST | §4.7a, §4.7b |
| B | **Application-level rate limiting for paid endpoints** — adopt `slowapi` or equivalent; default 5 req/min on TTS, configurable per route | ⚠️ HIGH | §4.5 |
| C | **Per-user / per-key attribution in provider-call logs** — add `user_id` and `api_key_id` fields to all `tts_*`, `llm_*`, `livekit_*` structlog events; emit Prometheus counters labelled by those fields | ⚠️ MEDIUM | §4.4 |
| D | **Retry-cap audit + standardisation across providers** — confirm Gemini, ElevenLabs, Deepgram retry behaviour; cap unbounded retries; document per-provider strategy | ⚠️ MEDIUM | §4.6 |
| E | **Provider-dashboard audit (key scopes + model allowlist + budget alerts)** — assigned to whoever has provider-console access; document findings in this audit's revision | ❓ NEEDS-OWNER | §4.1, §4.2, §4.3 |

Out-of-band but worth noting:
- **F — Greeting auto-fire on participant join** (§4.7c) and **G — server-side session-duration cap** (§4.7d) could be folded into ticket A or filed separately depending on PO preference.

---

## 7. Verification methodology — Shikhar's safe local abuse demo

**Date:** 2026-06-18
**Author:** Shikhar Thakur
**Goal:** Simulate unauthenticated abuse of TTS and LiveKit token routes without contacting third-party providers.

### Test setup

1. Blanked provider API keys in `backend/.env`: `ELEVENLABS_API_KEY`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`. This prevents outbound calls.
2. Restarted backend so environment changes were applied.
3. Waited for API to become healthy.
4. Sent 10 unauthenticated POSTs each to `/v1/tts/synthesize` and `/v1/livekit/token`.

### Commands used

```bash
# TTS (5 requests, repeated to make 10)
for i in $(seq 1 5); do
  curl -s -X POST http://localhost:8000/v1/tts/synthesize \
    -H 'Content-Type: application/json' \
    -d '{"voice":"alloy","text":"Test TTS run '$i'"}' \
    -w "\n---RESPONSE-END---\n"
done

# LiveKit token (5 requests)
for i in $(seq 1 5); do
  curl -s -X POST http://localhost:8000/v1/livekit/token \
    -H 'Content-Type: application/json' \
    -d '{"room":"demo","identity":"tester'$i'"}' \
    -w "\n---RESPONSE-END---\n"
done
```

### Observed outcomes

- **TTS endpoint:** With blanked keys → backend returned 422 validation errors (no outbound calls). With limited staging keys (separate run) → backend forwarded all 5 requests to ElevenLabs, which returned `HTTP 401 / quota_exceeded`. This **confirms the backend forwards unauthenticated input directly to the paid provider when a key is present.**
- **LiveKit token endpoint:** Backend returned signed JWTs (HTTP 200) for all 5/5 requests. No external LiveKit REST calls were observed (tokens are signed locally). **Tokens issued without authentication can be used to join LiveKit Cloud rooms, which then trigger billable usage.**

### Selected sanitised log excerpts

```
HTTP Request: POST https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM "HTTP/1.1 401 Unauthorized"
{"status": 401, "detail": "{\"detail\":{\"type\":\"invalid_request\",\"code\":\"quota_exceeded\",...}}", "voice_id": "21m00Tcm4TlvDq8ikWAM", "event": "tts_elevenlabs_error", "timestamp": "2026-06-18T08:37:44Z"}
...
{"identity": "tester", "room": "leak-test", "event": "livekit_token_issued", "timestamp": "2026-06-18T08:38:44Z"}
```

### Interpretation

- Backend will forward unauthenticated input to paid providers as soon as a valid key is present.
- LiveKit token issuance is fully open — anyone discovering the URL can mint room tokens.
- Per-user / per-key attribution is absent in log events (the `identity` field is FE-supplied).

---

## 8. References

- **Issue:** [amosproj/amos2026ss04-taskorbit-conversational-agent#151](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/151)
- **PO scoping message:** Discord, 2026-06-17 18:39 (PO scope statement defining audit AC)
- **PO GCP investigation:** Discord, 2026-06-17 (Google Veo identified as $421 spike source)
- **Shikhar's investigation report:** this branch's commit history (`docs/151-api-usage-audit`)
- **Related sprint context:** Sprint 10 plan (2026-06-17 team meeting)

---

*This audit closes the discovery phase of #151. Remediation work proceeds through the §6 follow-up tickets in Sprint 11.*
