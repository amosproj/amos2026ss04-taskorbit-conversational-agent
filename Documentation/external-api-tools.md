# External API Tools — TaskOrbit Conversational Agent

> **Scope.** This guide is for system admins who want to give an agent the
> ability to call an external HTTP API (REST endpoint, outbound webhook,
> CRM lookup, etc.) without writing any Python. Everything is config.
>
> The adapter lives in `backend/src/taskorbit/tools/generic_api.py` and
> plugs into the existing tool dispatcher. The routing system that
> decides which tool fires is described separately.

---

## What this is

Before #66, every external API the agent could call needed its own Python
class extending `BaseTool`. Adding a new API meant a code change, a PR, a
review, and a deploy.

The **Generic External Tool Adapter** is a single `BaseTool` subclass
(`GenericApiTool`) that interprets its behaviour at runtime from a JSON
config carried on the tool definition. New external tools are now config
edits, not code edits.

This unlocks two use cases at once:

- **REST API integrations** (weather lookups, CRM record fetches, internal
  microservices, etc.).
- **Outbound webhooks** (Slack incoming webhook, Zapier catch hook,
  Discord webhook). These are just HTTP POSTs, so the same adapter
  handles them.

Inbound webhooks (an external service POSTing events to TaskOrbit) are
out of scope for this adapter and would need a separate ticket.

---

## How to add an external tool

You edit the tool's `parameters` block directly in the agent config (via
the **Tools** section of the Agent Configuration page, or by editing the
saved JSON). The shape is below; every field is validated at runtime by
`taskorbit.tools.generic_api.parse_config`.

```jsonc
{
  "type": "external_api",
  "name": "lookup_weather",
  "description": "Use this tool to look up current weather for a city.",
  "parameters": {
    "request": {
      "method": "GET",
      "url": "https://api.weatherapi.com/v1/current.json",
      "headers": {
        "X-API-Key": "{{env.WEATHER_API_KEY}}"
      },
      "query": {
        "q": "{{args.city}}"
      },
      "timeout_seconds": 5
    },
    "response": {
      "extract": {
        "temperature_c": "current.temp_c",
        "condition": "current.condition.text"
      },
      "success_when": {
        "status_in": [200]
      }
    },
    "auth": {
      "allowed_env": ["WEATHER_API_KEY"]
    },
    "error_mapping": {
      "TIMEOUT": "The weather service is slow right now. Try again in a moment.",
      "HTTP_4XX": "I could not find weather data for that location."
    },
    "args_schema": {
      "type": "object",
      "required": ["city"],
      "properties": {
        "city": {
          "type": "string",
          "description": "City name in English."
        }
      }
    }
  }
}
```

When the LLM calls this tool with `{"city": "Berlin"}`, the adapter:

1. Validates the args against `args_schema`.
2. Substitutes templates (`{{args.city}}` becomes `Berlin`; `{{env.WEATHER_API_KEY}}` is resolved from the process environment).
3. Sends a `GET https://api.weatherapi.com/v1/current.json?q=Berlin` with the API key header.
4. Reads the response as JSON, walks the configured dot-paths, and returns a standardised envelope:

```json
{
  "status": 200,
  "data": {
    "temperature_c": 18.3,
    "condition": "Cloudy"
  },
  "raw": { /* the full upstream JSON, preserved for debugging */ },
  "headers": { /* response headers */ }
}
```

---

## Config reference

### `request` (required)

| Field             | Type    | Required | Notes                                                                            |
| ----------------- | ------- | -------- | -------------------------------------------------------------------------------- |
| `method`          | string  | yes      | One of `GET`, `POST`, `PUT`, `PATCH`, `DELETE`.                                  |
| `url`             | string  | yes      | Absolute URL. Supports `{{env.X}}` and `{{args.Y}}` substitution.                |
| `headers`         | object  | no       | String values. Substitution supported.                                            |
| `query`           | object  | no       | String values. Substitution supported.                                            |
| `body`            | any     | no       | JSON body (object / array / primitive). Substitution walks nested strings.       |
| `timeout_seconds` | number  | no       | Default `10`. Must be > 0.                                                       |

### `response` (optional)

| Field                       | Type   | Notes                                                                                  |
| --------------------------- | ------ | -------------------------------------------------------------------------------------- |
| `extract`                   | object | Maps stable output names to dot-paths in the response body (see "Extraction" below).   |
| `success_when.status_in`    | array  | List of integer HTTP statuses considered success. Default `[200..299]`.                |

### `auth` (optional, security-relevant)

| Field         | Type  | Notes                                                                                                |
| ------------- | ----- | ---------------------------------------------------------------------------------------------------- |
| `allowed_env` | array | Whitelist of env-var names that may be referenced via `{{env.NAME}}`. **Required when using `env`.** |

### `error_mapping` (optional)

Map of `ERROR_CODE -> human-friendly message`. Overrides the default
message for that code. See "Error codes" below.

### `args_schema` (optional but strongly recommended)

A minimal JSON-Schema-style description of the args this tool accepts.
Used both for runtime validation and for telling the LLM what to pass.
Supports `required`, `properties.<name>.type` (`string`, `integer`,
`number`, `boolean`, `object`, `array`).

---

## Template substitution

Two namespaces:

- `{{args.NAME}}` — runtime arguments supplied by the LLM. Supports
  nested keys via dot syntax: `{{args.user.id}}`.
- `{{env.NAME}}` — process environment variables. The name **must** be
  listed in `auth.allowed_env` or substitution fails with
  `TEMPLATE_INVALID`. This whitelist prevents a careless or malicious
  config from exfiltrating secrets like `AWS_SECRET_ACCESS_KEY`.

Substitution applies recursively to strings inside the `url`,
`headers`, `query`, and `body`. Missing args or unauthorised env vars
raise immediately rather than silently sending an incomplete request.

---

## Response extraction

The `response.extract` map pulls fields out of the upstream JSON and
exposes them under stable names. The path syntax is **dot-separated**:

```jsonc
"extract": {
  "temperature": "current.temp_c",
  "humidity": "current.humidity"
}
```

walks `body["current"]["temp_c"]` and `body["current"]["humidity"]`.

- A leading `$.` is accepted and stripped, so JSONPath-style paths like
  `$.data.value` work for the simple case.
- A bare `$` returns the whole body.
- Array indexing and wildcards are **not** supported in v1; if your API
  forces you into them, raise a follow-up so we can scope a JSONPath
  dep.
- Missing segments resolve to `null` rather than raising. A single
  missing field will not blow up an otherwise-successful response.

When `extract` is configured, the result envelope carries the
standardised shape under `data` AND keeps the original upstream payload
under `raw` so operators can still inspect what came back.

---

## Error codes

Every failure surfaces under a standardised envelope:

```json
{
  "error_code": "HTTP_4XX",
  "error_message": "The CRM could not find that record.",
  "error_detail": "upstream returned HTTP 404",
  "status": 404
}
```

| Code                | When it fires                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| `CONFIG_INVALID`    | The tool's config does not match the schema (e.g. unsupported method, missing URL).            |
| `ARGS_INVALID`      | The args supplied by the LLM violate `args_schema` (missing required key, wrong type).         |
| `TEMPLATE_INVALID`  | A `{{env.X}}` reference is not in `auth.allowed_env`, or a `{{args.Y}}` key was not supplied.  |
| `TIMEOUT`           | The HTTP request exceeded `request.timeout_seconds`.                                           |
| `NETWORK`           | Connection refused, DNS failure, SSL error, anything below the response layer.                 |
| `HTTP_4XX`          | Response status 400-499 and not in `success_when.status_in`.                                   |
| `HTTP_5XX`          | Response status 500-599 and not in `success_when.status_in`.                                   |
| `HTTP_UNEXPECTED`   | Response status is neither success nor 4xx/5xx (e.g. a 3xx, or 201 when only 200 was allowed). |
| `INVALID_RESPONSE`  | `extract` was configured but the response body could not be parsed as JSON.                    |

`error_mapping` overrides the human-readable `error_message` per code.
`error_detail` always carries the technical reason for logs and
debugging, regardless of mapping.

---

## Security model

The adapter is config-driven, which means a tool config is effectively
code. Two safety mechanisms keep the blast radius contained:

1. **Env-var whitelist** (`auth.allowed_env`). A `{{env.X}}` template
   reference fails with `TEMPLATE_INVALID` if `X` is not on the list,
   so a typo or a malicious config cannot leak unrelated secrets.
2. **Loud failures on missing data.** Missing args or unset env vars
   raise before the HTTP request fires, so the agent does not
   accidentally call an external service with `Bearer` and an empty key.

API keys themselves still live in the process environment, never in the
config. The config only references their names.

---

## Troubleshooting

| Symptom                                                                | Likely cause                                                                                                |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Tool result has `error_code: CONFIG_INVALID`                           | Open the config in the FE editor; `error_detail` names the failing field.                                   |
| Tool result has `error_code: TEMPLATE_INVALID` with `not in allowed_env` | Add the env var to `auth.allowed_env`.                                                                       |
| Tool result has `error_code: TEMPLATE_INVALID` with `was not provided` | LLM did not supply the arg. Tighten `args_schema.required` so the LLM is told to provide it.                |
| Tool result has `error_code: INVALID_RESPONSE`                         | Upstream returned non-JSON. Either remove `extract` or fix the upstream.                                    |
| Tool result has `error_code: HTTP_5XX`                                 | Upstream service is down or rate-limiting. Use `error_mapping.HTTP_5XX` to give the user a kinder message.  |

---

## Where it lives in the code

| Concern                                       | File                                                                       |
| --------------------------------------------- | -------------------------------------------------------------------------- |
| Tool implementation                           | `backend/src/taskorbit/tools/generic_api.py`                               |
| Tool type registration                        | `backend/src/taskorbit/types.py` (`ToolType.EXTERNAL_API`)                 |
| Dispatch wiring                               | `backend/src/taskorbit/orchestration/__init__.py` (`_dispatch_tool(tool, context, db, user_id)`) — `db` and `user_id` are threaded through so `AgentTransferTool` can reach custom agents; other tool types receive `tool_cls().execute(context)` as before |
| JSON schema (validates saved agent configs)   | `schemas/agent-task.schema.json` (`externalApiTool` + sub-schemas)         |
| Canonical example                             | `schemas/examples/agent-task.example.json` (`lookup_service_area` tool)    |
| Unit tests                                    | `backend/tests/test_generic_api_tool.py`                                   |
| Integration test against real httpbin         | `backend/tests/test_generic_api_integration.py` (run with `-m integration`) |
| FE form editor                                | `frontend/src/components/agent-config/ToolsSection.tsx` (`ExternalApiEditor`) |
| FE type definition                            | `frontend/src/types/agentConfig.ts` (`ExternalApiTool`)                    |

---

## Out of scope (potential follow-ups)

These were intentionally not built in #66 so the first version stays
focused. Open a new ticket if a real config needs any of them.

- OAuth2 flows / refresh tokens (auth is API-key / header only).
- File upload / multipart bodies (JSON body only).
- Streaming responses (single request → single response only).
- Retry-with-backoff on transient failures.
- Per-tool rate limiting.
- Full JSONPath in response extraction (currently dot-path + `$.` prefix
  only; no `[*]`, no filters).
- Inbound webhooks (external service → TaskOrbit). The adapter handles
  outbound webhooks for free, but inbound needs its own ticket
  (public endpoint, signature verification, event routing into
  active sessions).
