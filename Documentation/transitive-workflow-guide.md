# Transitive workflow dependencies

This guide explains how TaskOrbit resolves **transitive** prerequisite agents: when agent A depends on B and B depends on C, the orchestration engine runs **C → B → A** at runtime even if A only lists B in its configuration.

For a minimal test setup using `agent-a` / `agent-b` / `agent-c`, follow the **Voice walkthrough** section below.

> **Platform note:** TaskOrbit is **voice-first**. The typed text input is legacy and will be **removed in upcoming sprints**. All walkthroughs below use **mic + Send** and the **Proceed** card. Automated backend tests still use text requests.

---

## Concepts

| Term | Meaning |
|------|---------|
| **Direct dependency** | Agent IDs listed in **Prerequisite Steps** for that agent |
| **Transitive dependency** | Prerequisite agents inferred by loading saved configs from the database |

Example chain:

```text
Configuration (what you save):          Runtime order (what the engine runs):

  customer-entry ──► sales-qualification   1. identity-verification
  sales-qualification ──► identity-verification   2. sales-qualification
                                              3. customer-entry
```

The entry agent does **not** need to list every upstream step. Transitive expansion walks the graph (e.g. entry lists sales; sales lists identity → identity runs first).

---

## Prerequisites (voice)

From the repo root (or separate terminals):

```bash
docker compose up --build
# or: postgres + poetry run taskorbit-api + poetry run taskorbit-worker dev + npm run dev
```

The **LiveKit worker** must be running for voice:

```bash
cd backend
poetry run taskorbit-worker dev
```

Set in `backend/.env`: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.

Allow the **microphone** when the browser prompts. Each test run needs a **new session**.

---

## Example: customer entry with sales and identity

### Scenario

A customer opens the **main reception** agent and asks to buy something. Business rules require:

1. **Identity verification** — leaf agent, no prerequisites  
2. **Sales qualification** — depends on identity  
3. **Customer entry** — entry point; depends on sales only  

### Agent configuration

Save agents in this order (each prerequisite must exist before it can be selected in the UI):

**`identity-verification`** (save first)

| Field | Value |
|-------|--------|
| Agent ID | `identity-verification` |
| Display name | `Identity Verification` |
| Instructions | `You verify the customer's identity. Always start your reply with exactly: VERIFY:` |
| Greeting | `Identity check ready.` |
| STT / LLM / TTS | e.g. Deepgram `nova-3`, OpenAI `gpt-4o-mini`, ElevenLabs voice |
| Prerequisite Steps | *(empty)* |
| Allowed Handoffs | *(empty)* |

**`sales-qualification`** (save second)

| Field | Value |
|-------|--------|
| Agent ID | `sales-qualification` |
| Display name | `Sales Qualification` |
| Instructions | `You qualify purchase intent and product needs. Always start your reply with exactly: SALES:` |
| Greeting | `Sales qualification ready.` |
| Prerequisite Steps | `identity-verification` |
| Allowed Handoffs | *(empty)* |

Expected in saved JSON:

```json
"workflow_dependencies": ["identity-verification"]
```

**`customer-entry`** (save last; use as the chat entry agent)

| Field | Value |
|-------|--------|
| Agent ID | `customer-entry` |
| Display name | `Customer Entry` |
| Instructions | `You are the main reception agent. Always start your reply with exactly: ENTRY:` |
| Greeting | `Welcome to customer support. How can I help you today?` |
| Prerequisite Steps | `sales-qualification` only — do **not** add `identity-verification` |
| Allowed Handoffs | *(empty)* |

Expected in saved JSON:

```json
"workflow_dependencies": ["sales-qualification"]
```

### Configuration checklist

| Agent ID | `workflow_dependencies` |
|----------|---------------------------|
| `identity-verification` | `[]` |
| `sales-qualification` | `["identity-verification"]` |
| `customer-entry` | `["sales-qualification"]` |

Use **Save as new** in Agent Config so each agent is stored under **My agents** (`POST /v1/user-agents`). Hard-refresh the browser after saving if a prerequisite does not appear in the dropdown.

---

## Manual walkthrough (voice)

1. Agent Config → load **`customer-entry`** → **Update** if needed  
2. Chat → **Start session** — confirm **Voice session active**  
3. Session title should show **Customer Entry**  
4. Use the **mic**: tap to record, then **Send** to commit each turn (do not rely on the typed text box — it is being removed)

### Voice interaction pattern

| Action | How |
|--------|-----|
| User message | Mic → speak → **Send** |
| Confirm prerequisite | Click **Proceed** on the card **or** say **"proceed"**, **"yes"**, or **"ok"** into the mic |
| Run a workflow step | After Proceed, mic → **"continue"** → **Send** |

### Turn sequence

| Turn | You do | Expected |
|------|--------|----------|
| 1 | Start session | Greeting; title **Customer Entry** |
| 2 | Say: *I want to buy something* → **Send** | **Proceed** card for **Identity Verification** first (not Sales) |
| 3 | Click **Proceed** (or say *proceed*) | Acknowledgment to start identity step |
| 4 | Say: *continue* → **Send** | Reply starts with **`VERIFY:`** |
| 5 | Say: *continue* → **Send** | **Proceed** card for **Sales Qualification** |
| 6 | Click **Proceed** (or say *proceed*) | Acknowledgment to start sales step |
| 7 | Say: *continue* → **Send** | Reply starts with **`SALES:`** (not `ENTRY:`) |
| 8 | Say: *continue* → **Send** | Reply starts with **`ENTRY:`**; no further Proceed cards |

The persona prefixes (`VERIFY:`, `SALES:`, `ENTRY:`) are for verification in this example. In production, use normal business instructions; the engine behavior is the same.

The workflow confirmation card shows a **colored left border** (primary color for workflow steps) — that is intentional UI styling in `ConfirmationPrompt`. Clicking **Proceed** syncs workflow state to the LiveKit worker via the `workflow_state` data channel.

---

## Minimal alias mapping

The same graph can be tested with short IDs for QA:

| Example agents | Minimal test IDs | Reply prefix |
|----------------|------------------|--------------|
| `identity-verification` | `agent-c` | `STEP-C:` |
| `sales-qualification` | `agent-b` | `STEP-B:` |
| `customer-entry` | `agent-a` | `STEP-A:` |

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| No voice / agent silent | LiveKit worker running; `.env` keys; mic permission |
| Prerequisite missing from dropdown | Save prerequisite agents first; hard refresh; recreate agents if created before the `agent_id` config fix |
| First Proceed is Sales, not Identity | `sales-qualification` must list `identity-verification`; backend should log dependency enrichment |
| After Proceed, *continue* returns wrong persona | Restart backend + worker; ensure orchestration uses the routed agent’s config for the LLM prompt |
| Title shows intent name (e.g. General Inquiry) | Use latest frontend/backend; entry display name should remain in the session title |
| No Proceed card | Entry agent has prerequisites configured; STT/LLM/TTS models are set |
| UI Proceed but voice step wrong | Hard refresh; confirm `workflow_state` sync between UI and LiveKit session |

More detail: see the **Troubleshooting** table above and restart backend + worker if persona routing looks stale.

---

## Automated tests

Backend tests use text HTTP requests (independent of the UI text box):

```bash
cd backend
poetry run pytest tests/test_workflow_engine.py -q
```

Tests use `agent-a` / `agent-b` / `agent-c` IDs; behavior matches this example.
