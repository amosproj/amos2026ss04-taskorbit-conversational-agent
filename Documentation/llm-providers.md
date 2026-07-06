# LLM Providers and Error Handling

> **Scope.** This guide documents the LLM provider abstraction, the error
> taxonomy shared across providers, and how the orchestrator turns provider
> failures into user-facing responses and Prometheus metrics (ticket #197).
>
> The abstraction lives in `backend/src/taskorbit/integrations/llm/`. The
> orchestrator's handlers live in `backend/src/taskorbit/orchestration/__init__.py`.

---

## What this covers

Before #197, any LLM provider failure that was not `LLMConfigError` or a
Python built-in `TimeoutError` fell through the orchestrator's `except
Exception` and produced a generic "An unexpected error occurred." reply.
The most visible symptom (that triggered #197) was OpenAI conversations
returning that fallback whenever the account's quota was exhausted or a
transient auth issue hit, because those surfaced as `LLMAuthError` or
`LLMRateLimitError` and the orchestrator did not catch them.

Now every provider maps its SDK-specific failure modes to a shared
`LLMError` hierarchy, both orchestration paths (text and stream) catch
`LLMError` and return a clear, provider-agnostic response with a specific
metric label.

## Error taxonomy

All classes live in `backend/src/taskorbit/integrations/llm/errors.py`.

| Class | Base | Raised when |
|---|---|---|
| `LLMError` | `Exception` | Base for all provider-layer failures. Catch this to handle "the provider failed for some reason." |
| `LLMConfigError` | `LLMError` | Static config problem (missing API key, unknown provider, unsupported model). Detected before the request is sent. |
| `LLMTimeoutError` | `LLMError` | Request exceeded the per-call timeout. Values are per-provider: OpenAI 8s (`openai_client._REQUEST_TIMEOUT_SECONDS`), Gemini 10s (`gemini_client._REQUEST_TIMEOUT_MS`), Ollama 300s (`ollama_client._REQUEST_TIMEOUT_SECONDS`). OpenRouter timeouts surface from the SDK's `EdgeNetworkTimeoutResponseError`. |
| `LLMRateLimitError` | `LLMAPIError` | Provider returned HTTP 429 or an equivalent overload signal. Covers both transient throttling and quota-exhausted-billing on providers that share the 429 code (e.g. OpenAI). |
| `LLMAuthError` | `LLMAPIError` | Provider returned HTTP 401 or 403 (invalid, revoked, or forbidden key). |
| `LLMAPIError` | `LLMError` | Any other provider-side error (5xx, malformed responses, empty content, unknown SDK errors). |

`LLMRateLimitError` and `LLMAuthError` intentionally inherit from
`LLMAPIError` so a caller that only cares about "some API-side problem"
can catch the base and still cover the specific subclasses.

## Provider -> `LLMError` mapping

Each client normalises its vendor SDK's exceptions to the shared taxonomy
before the exception leaves the client. This is what lets the orchestrator
handle every provider with one set of `except` blocks.

| SDK / signal | OpenAI | Gemini | OpenRouter | Ollama |
|---|---|---|---|---|
| Auth | `openai.AuthenticationError` (401) | `genai_errors.ClientError` (401/403) | `ForbiddenResponseError`, `UnauthorizedResponseError` | `httpx.HTTPStatusError` (401 only; 403 currently falls through to `LLMAPIError`) |
| 429 / overload | `openai.RateLimitError` | `genai_errors.ClientError` (429) | `TooManyRequestsResponseError`, `ProviderOverloadedResponseError` | (n/a for local) |
| Timeout | `openai.APITimeoutError` | `genai_errors.ClientError` (408) | `EdgeNetworkTimeoutResponseError` | `httpx.TimeoutException` |
| Other API error | `openai.APIError` (base) | `genai_errors.APIError` | `OpenRouterError` (base) | `httpx.HTTPStatusError` (other), `httpx.HTTPError` |
| Empty response | mapped locally | mapped locally | mapped locally | mapped locally |

The `generate_stream` method delegates to `generate` on OpenRouter (its
free-tier SSE returns empty chunks), so the mapping above applies to
both entry points on that provider. For OpenAI, Gemini, and Ollama the
streaming methods have their own dedicated `except` chains that mirror
the non-streaming mapping.

The OpenRouter client also wraps `exc.body` through the
`_bounded_detail` helper (500-char cap) before it enters logs or the
user-visible LLMError message, so an oversized upstream error body
cannot bloat observability or the `ConversationResponse.error` field.

The mapping is verified by per-client tests: `test_openai_client.py`,
`test_gemini_client.py`, `test_openrouter_client.py`,
`test_ollama_client.py`. Whenever a new SDK error type needs to be
handled, add the mapping in the client and add a test that instantiates
that SDK error and asserts the raised `LLMError` subclass.

## Orchestrator behaviour

Both `process_message` (text) and `process_message_stream` (stream) in
`backend/src/taskorbit/orchestration/__init__.py` wrap the whole turn
with the same handler chain, in this order:

1. `LLMConfigError` -> config-specific error response (label `llm_config`).
2. `TimeoutError`, `LLMTimeoutError` -> timeout-specific error response
   (label `llm_timeout`). The caught exception is logged as `error=str(exc)`
   so on-call can tell which SDK raised it.
3. `LLMError` (base) -> provider-agnostic error response for auth, rate
   limit, other API errors, and any future `LLMError` subclass
   (label `llm_provider_error`).
4. `UnicodeEncodeError` -> encoding-specific error response
   (label `encoding_error`).
5. `ValueError` -> invalid-input error response (label `invalid_input`).
6. `Exception` -> last-resort generic fallback (label `runtime_error`).

Handler order matters: `LLMConfigError` and `LLMTimeoutError` both
inherit from `LLMError`, so their handlers MUST come before the
`LLMError` base handler, otherwise config errors would silently
downgrade to the generic `llm_provider_error` label and lose their
dedicated user message. This contract is defended by an inline comment
above the chain in both paths and by the regression test
`test_handler_ordering_llm_config_still_routes_to_llm_config_bucket`
in `test_orchestration.py`.

The user-facing reply for handler (3) is deliberately generic ("having
trouble reaching my language model provider right now"). The exact
failure detail (rate limit, auth, provider name, upstream reason) is
carried in the `error` field of `ConversationResponse` and in the log,
so on-call has full context without exposing internals to end users.

The polite reply reaches every entry point:
- `POST /v1/conversations/process` returns it in `response.reply.content`.
- `POST /v1/conversations/stream` forwards it in the SSE error event as
  `{"type": "error", "message": <technical>, "reply": <polite>}`, and
  persists the assistant reply to the DB for symmetry with `/process`.
- LiveKit voice worker (`livekit_agent/llm.py`) speaks the polite reply
  through TTS on both early-exit errors and mid-stream provider failures
  (previously a mid-stream error caused a half-sentence trail-off into
  silence), and preserves `_locked_intent_name` /
  `_completed_workflow_steps` on error responses so a transient blip
  does not strand the session mid-workflow.

The intent router's own LLM call is wrapped by
`backend/src/taskorbit/intent/__init__.py` and re-raises `LLMError` up
to these handlers. Without that re-raise, intent-detection failures
would be masked as a low-confidence clarification and the user would
never see the provider error message.

## Metric labels

Every label value on `taskorbit_conversation_errors_total{error_type=...}`
is pre-registered in the allow-list in
`backend/src/taskorbit/observability/metrics.py::configure_default_metrics`
so Prometheus exposes them from the first scrape, even before a matching
error has been seen.

| Label | Emitted by | Covers |
|---|---|---|
| `llm_config` | orchestrator handler (1) | Static configuration errors caught before the request is sent. |
| `llm_timeout` | orchestrator handler (2) | Both Python `TimeoutError` and `LLMTimeoutError` from any provider. |
| `llm_provider_error` | orchestrator handler (3) | Every non-timeout `LLMError` subclass: auth, rate limit, any other API error. |
| `encoding_error` | orchestrator handler (4) | `UnicodeEncodeError` on the reply path (rare). |
| `invalid_input` | orchestrator handler (5) | `ValueError` raised inside the turn (malformed structured input). |
| `runtime_error` | orchestrator handler (6) | Last-resort generic bucket for any other `Exception`. |
| `unhandled` | FastAPI middleware in `api/main.py` | Exceptions that escape the orchestrator entirely and reach the app-level error handler. |

The provider-side clients also emit `taskorbit_llm_requests_total{provider,
model, status}` with `status` in `{success, auth, rate_limit, timeout,
api}`. Query both counters together to distinguish "our orchestrator
caught it" from "the provider returned it." OpenRouter's client uses
`status="auth"` for both the pre-#197 `ForbiddenResponseError` path and
the new `UnauthorizedResponseError` path so alerts do not need to
enumerate SDK-specific subclasses.

## Adding a new provider

1. Add a class that satisfies the `LLMClient` Protocol (see `base.py`) in a
   new `<provider>_client.py` under `backend/src/taskorbit/integrations/llm/`.
   `LLMClient` is a `typing.Protocol`, so no explicit inheritance is needed;
   implementing `generate` and `generate_stream` with the required
   signatures is enough. Use `runtime_checkable` if you need `isinstance`.
2. Inside `generate` and `generate_stream`, catch the SDK's own exception
   types and re-raise them as the appropriate `LLMError` subclass
   (`LLMAuthError`, `LLMRateLimitError`, `LLMTimeoutError`, `LLMAPIError`).
   Preserve the original message via `from exc`.
3. Emit `llm_requests_total` with the correct `status` label for each
   failure branch (see any existing client for the pattern).
4. Wire the client into `factory.py::get_llm_client` behind the provider
   enum value.
5. Add a test module `test_<provider>_client.py` that instantiates each
   SDK error and asserts the raised `LLMError` subclass. Match the
   pattern in `test_openai_client.py`.
6. If you are introducing a new metric label, register it in
   `observability/metrics.py::configure_default_metrics` and add a row
   to the table above.
