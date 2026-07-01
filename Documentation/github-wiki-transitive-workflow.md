# Transitive Workflow Dependencies

TaskOrbit runs **multi-agent prerequisite chains** over **voice**. When agent A depends on B and B depends on C, the engine runs **C → B → A** at runtime — even when A only lists B in Agent Config.

> **Note:** TaskOrbit is **voice-first**. The typed text input is legacy and will be **removed in upcoming sprints**. Manual testing uses **mic → Send** and the **Proceed** card. Backend automated tests still use text HTTP requests.

---

## Direct vs transitive

| Term | Meaning |
|------|---------|
| **Direct dependency** | Agent IDs in **Prerequisite Steps** for that agent |
| **Transitive dependency** | Upstream agents inferred from saved configs in the database |

**Example configuration:**

```text
customer-entry ──► sales-qualification
sales-qualification ──► identity-verification
```

**Runtime order:** identity-verification → sales-qualification → customer-entry

The entry agent does **not** need to list every upstream step.

---

## Prerequisites

```bash
# From repo root
docker compose up --build

# LiveKit worker (required for voice)
cd backend
poetry run taskorbit-worker dev
```

Set in `backend/.env`:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `DEEPGRAM_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`

Allow **microphone** in the browser. Use a **new session** for each test run.

---

## Example agents

Save in this order: **identity → sales → entry** (use **Save as new** in Agent Config).

### 1. `identity-verification` (leaf)

| Field | Value |
|-------|--------|
| Agent ID | `identity-verification` |
| Display name | Identity Verification |
| Instructions | `You verify the customer's identity. Always start your reply with exactly: VERIFY:` |
| Greeting | `Identity check ready.` |
| STT / LLM / TTS | e.g. `nova-3`, `gpt-4o-mini`, any ElevenLabs voice |
| Prerequisite Steps | *(empty)* |
| Allowed Handoffs | *(empty)* |

### 2. `sales-qualification`

| Field | Value |
|-------|--------|
| Agent ID | `sales-qualification` |
| Display name | Sales Qualification |
| Instructions | `You qualify purchase intent and product needs. Always start your reply with exactly: SALES:` |
| Greeting | `Sales qualification ready.` |
| Prerequisite Steps | `identity-verification` |
| Allowed Handoffs | *(empty)* |

Expected in saved JSON:

```json
"workflow_dependencies": ["identity-verification"]
```

### 3. `customer-entry` (open in Chat)

| Field | Value |
|-------|--------|
| Agent ID | `customer-entry` |
| Display name | Customer Entry |
| Instructions | `You are the main reception agent. Always start your reply with exactly: ENTRY:` |
| Greeting | `Welcome to customer support. How can I help you today?` |
| Prerequisite Steps | `sales-qualification` only — do **not** add `identity-verification` |
| Allowed Handoffs | *(empty)* |

Expected in saved JSON:

```json
"workflow_dependencies": ["sales-qualification"]
```

Hard-refresh after saving if prerequisites are missing from the dropdown.

---

## Voice test script

1. Agent Config → load **`customer-entry`** → **Update**
2. Chat → **Start session** — confirm **Voice session active**
3. Session title should stay **Customer Entry**
4. Every user turn: **mic → speak → Send**

| Turn | You do | Pass if |
|------|--------|---------|
| 1 | Say *I want to buy something* → **Send** | **Proceed** for **Identity Verification** first (not Sales) |
| 2 | Click **Proceed** (or say *proceed* / *yes*) | Acknowledgment for identity step |
| 3 | Say *continue* → **Send** | Reply contains **`VERIFY:`** |
| 4 | Say *continue* → **Send** | **Proceed** for **Sales Qualification** |
| 5 | Click **Proceed** | Acknowledgment for sales step |
| 6 | Say *continue* → **Send** | Reply contains **`SALES:`** (not **`ENTRY:`**) |
| 7 | Say *continue* → **Send** | Reply contains **`ENTRY:`**; no more Proceed cards |

**Voice confirm words:** `yes`, `proceed`, `sure`, `ok`, `go ahead`

Extra text after each prefix is OK — only **order** and **prefix** matter.

---

## Minimal test IDs (QA)

Same graph with short names for internal QA:

| Realistic ID | QA ID | Prefix |
|--------------|-------|--------|
| `identity-verification` | `agent-c` | `STEP-C:` |
| `sales-qualification` | `agent-b` | `STEP-B:` |
| `customer-entry` | `agent-a` | `STEP-A:` |

---

## Workflow Proceed card

The **Proceed / Cancel** card shows a **colored left border** on workflow steps. That is intentional UI styling, not an error.

Clicking **Proceed** syncs workflow state to the LiveKit worker via the `workflow_state` data channel.

---

## UI Proceed sync test (optional)

Repeat the voice script once using **UI Proceed only** (do not say *yes* into the mic) for the Identity and Sales confirmation steps. Voice *continue* turns should still produce the correct prefixes in order.

---

## Automated tests

```bash
cd backend
poetry run pytest tests/test_workflow_engine.py -q
```

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No voice reply | Worker running; LiveKit / Deepgram / ElevenLabs keys in `.env` |
| Prerequisite missing in dropdown | Save upstream agents first; hard refresh |
| Sales Proceed before Identity | `sales-qualification` must list `identity-verification` |
| Wrong persona after Proceed | Restart backend + worker |
| Title shows "General Inquiry" | Use latest build; title should stay **Customer Entry** |
| UI Proceed but wrong voice step | Worker `workflow_state` sync; hard refresh |
| No Proceed card | Entry agent has prerequisites; STT/LLM/TTS models filled |

---

## Related repository documentation

- `Documentation/transitive-workflow-guide.md` — full guide
- `Documentation/demo-2-transitive-chain.md` — minimal `agent-a/b/c` voice demo
- `Documentation/demo-3-voice-ui-proceed-sync.md` — UI Proceed + LiveKit sync
- `Documentation/demo-index.md` — demo index
