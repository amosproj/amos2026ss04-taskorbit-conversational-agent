# Transitive workflow dependencies

This guide explains how TaskOrbit resolves **transitive** prerequisite agents: when agent A depends on B and B depends on C, the orchestration engine runs **C → B → A** at runtime even if A only lists B in its configuration.

For a minimal test setup using `agent-a` / `agent-b` / `agent-c`, see [demo-2-transitive-chain.md](./demo-2-transitive-chain.md).

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

## Manual walkthrough

1. Agent Config → load **`customer-entry`** → **Update** if needed  
2. Chat → **Start session** (new session per run)  
3. Session title should show **Customer Entry**  
4. Prefer the text input (**Ask from Orbit**) for predictable workflow steps; voice is supported with UI **Proceed** sync — see [demo-3-voice-ui-proceed-sync.md](./demo-3-voice-ui-proceed-sync.md)

### Message sequence

```text
i want to buy something
[Proceed — Prerequisite: Identity Verification]
continue
continue
[Proceed — Prerequisite: Sales Qualification]
continue
continue
```

Use plain `continue` (avoid trailing punctuation that can affect intent routing).

### Expected behavior

| Step | Action | Expected |
|------|--------|----------|
| 1 | Start session | Greeting; title **Customer Entry** |
| 2 | `i want to buy something` | **Proceed** card for **Identity Verification** first (not Sales) |
| 3 | **Proceed** | Acknowledgment to start identity step |
| 4 | `continue` | Reply starts with **`VERIFY:`** |
| 5 | `continue` | **Proceed** card for **Sales Qualification** |
| 6 | **Proceed** | Acknowledgment to start sales step |
| 7 | `continue` | Reply starts with **`SALES:`** (not `ENTRY:`) |
| 8 | `continue` | Reply starts with **`ENTRY:`**; no further Proceed cards |

The persona prefixes (`VERIFY:`, `SALES:`, `ENTRY:`) are for verification in this example. In production, use normal business instructions; the engine behavior is the same.

The workflow confirmation card shows a **colored left border** (primary color for workflow steps) — that is intentional UI styling in `ConfirmationPrompt`.

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
| Prerequisite missing from dropdown | Save prerequisite agents first; hard refresh; recreate agents if created before the `agent_id` config fix |
| First Proceed is Sales, not Identity | `sales-qualification` must list `identity-verification`; backend should log dependency enrichment |
| After Proceed, `continue` returns wrong persona | Restart backend; ensure orchestration uses the routed agent’s config for the LLM prompt |
| Title shows intent name (e.g. General Inquiry) | Use latest frontend/backend; entry display name should remain in the session title |
| No Proceed card | Entry agent has prerequisites configured; STT/LLM/TTS models are set |

More detail: [demo-2-transitive-chain.md](./demo-2-transitive-chain.md#if-something-fails).

---

## Automated tests

```bash
cd backend
poetry run pytest tests/test_workflow_engine.py -q
```

Tests use `agent-a` / `agent-b` / `agent-c` IDs; behavior matches this example.

---

## Voice

Start the LiveKit worker for voice sessions:

```bash
cd backend
poetry run taskorbit-worker dev
```

Requires LiveKit, Deepgram, and ElevenLabs credentials in `backend/.env`. Mixed mode (voice session + text **Proceed** / **continue**) is the most reliable way to exercise workflow steps over voice.
