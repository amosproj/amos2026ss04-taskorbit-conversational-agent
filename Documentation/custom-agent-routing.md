# Custom Agent Routing — TaskOrbit Conversational Agent

> **Scope.** This guide explains how TaskOrbit routes a conversation to the
> correct agent, including how custom (user-saved) agents participate in both
> the manual UI path and the automatic intent-driven path. It covers the
> backend orchestration pipeline, security scoping, and the frontend handoff UX.

---

## Overview

TaskOrbit supports two distinct ways to transfer a conversation from one agent
to another:

| Path | Trigger | Who decides |
|---|---|---|
| **Manual transfer** | User picks an agent from the UI dropdown | User |
| **Auto transfer** | LLM dispatches the `agent_transfer` tool mid-conversation | Orchestrator / LLM |

Both paths ultimately reach the same `ConversationOrchestrator.process_message`
pipeline and produce the same `ConversationResponse`, but they enter at
different points (step 0a vs. step 4).

---

## Orchestration pipeline (step order)

```
User message
     │
     ▼
 0a. Manual transfer short-circuit
     │  If request.manual_transfer is set, bypass steps 1–6 entirely
     │  and delegate to _handle_manual_transfer.
     │  On completion, re-enter the pipeline under the new agent (step 1+).
     │
     ▼
  1. Intent detection
  2. Agent selection (AgentRegistry.create_by_name)
  3. System prompt construction
  4. LLM call → reply text + optional tool_invoked
  5. Tool dispatch (_dispatch_tool) ← agent_transfer fires here
  6. Response assembly → ConversationResponse
```

### Step 0a — Manual transfer short-circuit

`_handle_manual_transfer` resolves the target agent in this order:

1. **By ID** (`target_agent_id`) — looks up `AgentConfiguration` by primary
   key, user-scoped (see Security section).
2. **By name** (`target_agent_name`) — fallback when no ID is provided,
   also user-scoped.
3. **Built-in template** — if neither user copy nor ID resolves, the
   orchestrator falls back to the matching built-in template (e.g.
   `SalesAgent`).

After the target config is loaded the orchestrator clears
`manual_transfer=None` on the forwarded request (recursion guard) and
re-enters the full pipeline (steps 1–6) under the new agent's persona
with the full conversation history preserved (AC3).

### Step 5 — Auto transfer via `agent_transfer` tool

When the LLM includes an `agent_transfer` tool call in its reply,
`_dispatch_tool` constructs `AgentTransferTool(db=db, user_id=user_id)` and
calls `execute(context)`. The tool:

1. Reads `targets[0]` from `context["parameters"]`.
2. Calls `_is_valid_target(target_id)`:
   - Checks built-in agent names first (no DB required).
   - Falls back to `get_agent_configuration_by_id(db, target_id, user_id=user_id)`
     when a DB session is available.
3. Returns `{"selected_agent": target_id}` on success or
   `{"error": "Unknown agent"}` on failure.

**UUID normalization:** target IDs that look like custom-agent UUIDs
(matching `/^[0-9a-f]{8}-…-[0-9a-f]{12}$/i`) are passed through untouched.
Only built-in slugs (e.g. `technical-support-agent`) are slug-normalized to
their registry key (`technical_support`). This prevents hyphen corruption of
custom agent UUIDs.

---

## Agent types

| Type | Defined in | Resolved by |
|---|---|---|
| Built-in | `agents/` Python classes | `AgentRegistry._REGISTRY` keyword lookup |
| Custom (user-saved) | `agent_configurations` DB table | `AgentRegistry.create_by_name` DB fallback / `AgentRegistry.create_custom` |

`CustomAgent` is never in `_REGISTRY` and is never matched by intent
detection. It is only constructed via `AgentRegistry.create_custom()` — called
from `_handle_manual_transfer` and the `create_by_name` DB fallback. This
prevents the string `"custom"` from accidentally matching an intent keyword.

---

## Security — user scoping

All agent DB lookups are scoped to the authenticated user so one user cannot
execute under another user's saved agent config.

### `get_agent_configuration_by_id`

```python
query = select(AgentConfiguration).where(AgentConfiguration.id == agent_id)
if user_id is not None:
    query = query.where(
        (AgentConfiguration.user_id == user_id) | (AgentConfiguration.user_id.is_(None))
    )
```

`user_id IS NULL` rows are global/template configs that any user may read.
The function returns `None` for both missing rows and rows owned by a
different user — it does not distinguish between the two to avoid an
existence oracle.

### `get_agent_configuration_by_name`

```python
if user_id is not None:
    query = query.where(AgentConfiguration.user_id == user_id)
else:
    # Fail-closed: unauthenticated callers see global templates only.
    query = query.where(AgentConfiguration.user_id.is_(None))
```

When `user_id=None` (e.g. the voice path before full auth is wired),
only global template rows (NULL `user_id`) are returned. This prevents
a voice session from resolving another user's custom agent by name.

### `_dispatch_tool` threading

`_dispatch_tool(self, tool, context, db=None, user_id=None)` receives both
the DB session and the authenticated `user_id` from `process_message`, and
passes them to `AgentTransferTool(db=db, user_id=user_id)` at construction
time. This ensures the auto-tool path applies the same ownership check as the
manual path.

---

## Frontend UX — agent handoff flow

### Manual transfer (text path)

1. User opens the route dropdown (`@` button in `InCallControls`) and picks
   an agent.
2. `handleRoutingTargetChange` fires immediately:
   - Sets the routing badge (`routedAgent`).
   - Appends a `"Transferring you to <name>…"` transcript entry.
   - Plays TTS announcement via `playSynthesizedSpeech`.
3. User sends their message. `handleSendText` includes
   `manual_transfer: { target_agent_id, target_agent_name }` in the request.
4. On success, `handleSendText` swaps the full agent config via
   `setActiveAgent` so subsequent messages run under the new agent.
5. On failure (target not found or backend rejects), an explicit
   `[Could not transfer to <name>]` marker is appended and the badge reverts.

### Auto transfer (voice and text paths)

When the backend's `response.tool_invoked.type === "agent_transfer"`:
- **Text path:** `handleSendText` in `ConversationalChat.tsx` fetches the
  user's agent list, matches the target ID, and calls `setActiveAgent`.
  A `[Transferred to <name>]` transcript marker is appended.
- **Voice path:** `worker.py` reads `agent._pending_handoff_target` after
  `generate_reply()` completes and publishes `{"type": "agent_handoff", "target": "<id>"}`
  on the `taskorbit.agent_handoff` LiveKit data topic. The frontend hook
  `useAgentHandoff` receives this, resolves the agent, and calls
  `setActiveAgent`.

### In-call agent identity strip

During an active call, a compact strip at the top of the transcript card
shows the current agent's initials and name. When `setActiveAgent` fires
(from any path above), a `useEffect` detects the name change and shows a
`↔ from [Previous Agent]` badge for the remainder of the call.

### Configuring transfer targets (#203)

The **Target agents** field on an `agent_transfer` tool (Agent Config →
Tools section) is a dropdown listing every available agent by name —
built-ins and the user's saved custom agents — instead of a free-text ID
input:

- Selecting an agent stores `entry.id`, the same stable identifier
  `resolve_transfer_target` resolves directly: the hyphenated template slug
  for built-ins (`sales-agent`) or the UUID for custom agents. The name
  shown in the dropdown is display-only; the ID is what's persisted in
  `targets`.
- Already-selected agents appear disabled in the list so the same target
  can't be added twice.
- If the agent list fails to load, the field falls back to the original
  free-text ID input.

---

## Voice path — limitations

The LiveKit voice worker currently runs with `user_id=None` because the
token metadata does not yet carry an authenticated user claim. Consequences:

- By-name custom-agent resolution is limited to global/template configs
  (fail-closed behaviour — see Security section).
- By-id resolution via `agent_transfer` tool works for global templates but
  not for user-owned `AgentConfiguration` rows (no ownership claim to match).

**When JWT auth lands:** wire the authenticated `user_id` into the LiveKit
token metadata, read it in `worker.py`, and pass it to
`build_default_agent(user_id=user_id)`. The `OrchestratorAgent` already
accepts `user_id` and forwards it to `process_message` — no further backend
changes needed.

---

## Where it lives in the code

| Concern | File |
|---|---|
| Orchestration pipeline + step 0a | `backend/src/taskorbit/orchestration/__init__.py` |
| Manual transfer resolution | `orchestration/__init__.py` → `_handle_manual_transfer` |
| Auto-tool dispatch wiring | `orchestration/__init__.py` → `_dispatch_tool` |
| `AgentTransferTool` + `_is_valid_target` | `backend/src/taskorbit/tools/agent_transfer.py` |
| `AgentRegistry` + `CustomAgent` | `backend/src/taskorbit/agents/` |
| DB lookups with user scoping | `backend/src/taskorbit/database/crud.py` |
| Voice path agent + `user_id` threading | `backend/src/taskorbit/livekit_agent/llm.py` |
| Voice path session builder | `backend/src/taskorbit/livekit_agent/session.py` |
| Frontend routing dropdown + badge | `frontend/src/components/chat/InCallControls.tsx` |
| Frontend transfer execution + failure UX | `frontend/src/components/ConversationalChat.tsx` |
| Voice handoff LiveKit hook | `frontend/src/hooks/useAgentHandoff.ts` |
| Agent config CRUD + copy-on-write | `backend/src/taskorbit/database/crud.py` |
| User-agents REST API | `backend/src/taskorbit/api/routes/user_agents.py` |

---

## Tests

| Test file | What it covers |
|---|---|
| `tests/test_orchestration.py` | End-to-end `process_message` with mock DB — auto-transfer to custom agent succeeds through `_dispatch_tool` wiring |
| `tests/test_orchestration.py` | Cross-user `get_agent_configuration_by_id` regression — user A cannot load user B's config |
| `tests/test_agent_transfer.py` | `AgentTransferTool._is_valid_target` with and without DB session |
| `tests/test_custom_agent_routing.py` | Manual transfer short-circuit, recursion guard, name vs. ID precedence |
| `tests/test_crud.py` | `get_agent_configuration_by_id` and `get_agent_configuration_by_name` user scoping |
