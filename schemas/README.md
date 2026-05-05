# Schema Foundation

This directory contains the initial JSON Schema contract for TaskOrbit task and agent configuration.

## Files

- `agent-task.schema.json`: Canonical schema definition for `task` + `agent` configuration.
- `examples/agent-task.example.json`: Example payload that follows the schema.

## Covered fields (issue #6)

- Task definition:
  - `name`, `description`
  - `required_inputs`
  - `workflow_steps`
- Agent definition:
  - metadata (`display_name`, `persona`, `description`)
  - `instruction`
  - `first_message`: object `{ "type": "text", "message", "prompt" }` (see `frontend/src/types/agentConfig.ts`)
  - `variables` for session state
  - technical provider configuration for `stt`, `tts`, `llm`
  - tools as a discriminated union on `type`:
    - `data_extraction` — `params[]` (`ToolParam`: `variable_name`, `description`, `type`, `required`)
    - `end_call` — no `params` / `targets`
    - `agent_transfer` — `targets[]` (non-empty)
    - Aligns with `ToolDefinition` in `frontend/src/types/agentConfig.ts`

## Notes

- This is the first schema iteration (`schema_version: 1.0.0`).
- Runtime orchestration behavior and persistence logic are not part of this schema file.
