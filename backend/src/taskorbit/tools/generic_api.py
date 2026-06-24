"""Generic external-API adapter tool (#66).

`GenericApiTool` is a single BaseTool subclass whose behaviour is fully
driven by configuration carried on `ToolDefinition.parameters`. This
lets system admins add new external tools (CRM lookups, weather APIs,
Slack/Zapier outbound webhooks, etc.) by writing a config block instead
of new Python code.

The module covers:
- The parsed config representation (`GenericApiConfig`) and `parse_config`.
- `{{env.X}}` and `{{args.Y}}` template substitution with an env-var
  whitelist (`auth.allowed_env`) so a malicious or careless config
  cannot exfiltrate arbitrary process env vars.
- Dot-path response extraction (`extract_path` / `extract_response`) so
  the LLM sees a stable shape regardless of vendor JSON.
- Standardised error envelope (`build_error`) with the ERROR_* code
  taxonomy so every failure surfaces the same way (#66 AC3).
- The async `execute` that wires everything together against httpx.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from taskorbit.logging.setup import get_logger
from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Config schema
# ---------------------------------------------------------------------------

_SUPPORTED_METHODS: frozenset[str] = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_TIMEOUT_SECONDS: float = 10.0
_DEFAULT_SUCCESS_STATUSES: tuple[int, ...] = tuple(range(200, 300))

# {{env.NAME}} or {{args.NAME}} — captures the namespace and the dotted key.
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*(env|args)\.([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")

# Standardised error codes (#66 stage 5, AC3). Every GenericApiTool failure
# surfaces under one of these so the LLM and downstream observability can
# branch on a stable identifier rather than parsing free-text messages.
ERROR_CONFIG_INVALID = "CONFIG_INVALID"
ERROR_ARGS_INVALID = "ARGS_INVALID"
ERROR_TEMPLATE_INVALID = "TEMPLATE_INVALID"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_NETWORK = "NETWORK"
ERROR_HTTP_4XX = "HTTP_4XX"
ERROR_HTTP_5XX = "HTTP_5XX"
ERROR_HTTP_UNEXPECTED = "HTTP_UNEXPECTED"
ERROR_INVALID_RESPONSE = "INVALID_RESPONSE"

_DEFAULT_ERROR_MESSAGES: dict[str, str] = {
    ERROR_CONFIG_INVALID: "The external tool is misconfigured.",
    ERROR_ARGS_INVALID: "The arguments supplied to the tool are invalid.",
    ERROR_TEMPLATE_INVALID: "The tool configuration referenced a value that is not available.",
    ERROR_TIMEOUT: "The external service did not respond in time.",
    ERROR_NETWORK: "Could not reach the external service.",
    ERROR_HTTP_4XX: "The external service rejected the request.",
    ERROR_HTTP_5XX: "The external service is unavailable.",
    ERROR_HTTP_UNEXPECTED: "The external service returned an unexpected status.",
    ERROR_INVALID_RESPONSE: "The external service returned a response we could not parse.",
}


@dataclass(frozen=True)
class GenericApiConfig:
    """Parsed and validated representation of an external-tool config.

    Built from the raw `ToolDefinition.parameters` dict via `parse_config`.
    Frozen so callers cannot mutate it after parsing; substitution returns
    fresh values.
    """

    method: str
    url: str
    headers: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    extract: dict[str, str] = field(default_factory=dict)
    success_statuses: tuple[int, ...] = _DEFAULT_SUCCESS_STATUSES
    allowed_env: frozenset[str] = field(default_factory=frozenset)
    error_mapping: dict[str, str] = field(default_factory=dict)
    args_schema: dict[str, Any] = field(default_factory=dict)


class GenericApiConfigError(ValueError):
    """Raised when ToolDefinition.parameters is malformed for an EXTERNAL_API tool."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_config(raw: dict[str, Any]) -> GenericApiConfig:
    """Parse a raw `ToolDefinition.parameters` dict into a `GenericApiConfig`.

    Raises `GenericApiConfigError` with a precise reason if the config is
    missing required fields, has the wrong types, or names an unsupported
    HTTP method.
    """
    if not isinstance(raw, dict):
        raise GenericApiConfigError("parameters must be a JSON object")

    request = raw.get("request")
    if not isinstance(request, dict):
        raise GenericApiConfigError("parameters.request is required and must be an object")

    method = str(request.get("method", "")).upper().strip()
    if method not in _SUPPORTED_METHODS:
        raise GenericApiConfigError(
            f"parameters.request.method must be one of {sorted(_SUPPORTED_METHODS)}, got '{method}'"
        )

    url = request.get("url")
    if not isinstance(url, str) or not url.strip():
        raise GenericApiConfigError(
            "parameters.request.url is required and must be a non-empty string"
        )

    headers = request.get("headers") or {}
    if not isinstance(headers, dict):
        raise GenericApiConfigError("parameters.request.headers must be an object if present")

    query = request.get("query") or {}
    if not isinstance(query, dict):
        raise GenericApiConfigError("parameters.request.query must be an object if present")

    body = request.get("body")  # None / dict / list / str all allowed

    timeout_raw = request.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout_seconds = float(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise GenericApiConfigError("parameters.request.timeout_seconds must be a number") from exc
    if timeout_seconds <= 0:
        raise GenericApiConfigError("parameters.request.timeout_seconds must be > 0")

    response = raw.get("response") or {}
    if not isinstance(response, dict):
        raise GenericApiConfigError("parameters.response must be an object if present")

    extract = response.get("extract") or {}
    if not isinstance(extract, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in extract.items()
    ):
        raise GenericApiConfigError(
            "parameters.response.extract must map string keys to string paths"
        )

    success_when = response.get("success_when") or {}
    status_in = success_when.get("status_in")
    if status_in is None:
        success_statuses = _DEFAULT_SUCCESS_STATUSES
    else:
        if not isinstance(status_in, list) or not all(isinstance(s, int) for s in status_in):
            raise GenericApiConfigError(
                "parameters.response.success_when.status_in must be a list of integers"
            )
        success_statuses = tuple(status_in)

    auth = raw.get("auth") or {}
    if not isinstance(auth, dict):
        raise GenericApiConfigError("parameters.auth must be an object if present")
    allowed_env_raw = auth.get("allowed_env") or []
    if not isinstance(allowed_env_raw, list) or not all(
        isinstance(s, str) for s in allowed_env_raw
    ):
        raise GenericApiConfigError("parameters.auth.allowed_env must be a list of strings")
    allowed_env = frozenset(allowed_env_raw)

    error_mapping = raw.get("error_mapping") or {}
    if not isinstance(error_mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in error_mapping.items()
    ):
        raise GenericApiConfigError(
            "parameters.error_mapping must map string codes to string messages"
        )

    args_schema = raw.get("args_schema") or {}
    if not isinstance(args_schema, dict):
        raise GenericApiConfigError("parameters.args_schema must be an object if present")

    return GenericApiConfig(
        method=method,
        url=url,
        headers=headers,
        query=query,
        body=body,
        timeout_seconds=timeout_seconds,
        extract=extract,
        success_statuses=success_statuses,
        allowed_env=allowed_env,
        error_mapping=error_mapping,
        args_schema=args_schema,
    )


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------


class TemplateSubstitutionError(ValueError):
    """Raised when a template references an unavailable env var or args key."""


def _lookup(namespace: str, key: str, args: dict[str, Any], allowed_env: frozenset[str]) -> str:
    """Resolve a single `{{namespace.key}}` reference to its substituted value.

    `env` references are gated by `allowed_env`; a reference to a name not
    on the whitelist raises rather than silently leaking or skipping.
    `args` supports nested keys with dot syntax (e.g. `{{args.user.id}}`).
    """
    if namespace == "env":
        if key not in allowed_env:
            raise TemplateSubstitutionError(f"env var '{key}' is not in auth.allowed_env whitelist")
        value = os.environ.get(key)
        if value is None:
            raise TemplateSubstitutionError(
                f"env var '{key}' is not set in the process environment"
            )
        return value

    if namespace == "args":
        cursor: Any = args
        for segment in key.split("."):
            if not isinstance(cursor, dict) or segment not in cursor:
                raise TemplateSubstitutionError(f"args key '{key}' was not provided")
            cursor = cursor[segment]
        if cursor is None:
            raise TemplateSubstitutionError(f"args key '{key}' is null")
        return str(cursor)

    # _TEMPLATE_PATTERN restricts to env|args, so this branch is unreachable
    # in practice; kept defensive for future namespace additions.
    raise TemplateSubstitutionError(f"unknown template namespace '{namespace}'")


def substitute_string(template: str, args: dict[str, Any], allowed_env: frozenset[str]) -> str:
    """Replace every `{{env.X}}` / `{{args.Y}}` reference in `template`.

    Returns the fully substituted string. Raises `TemplateSubstitutionError`
    on the first unresolved or unauthorised reference; we fail loudly so a
    misconfigured tool surfaces as a config error rather than silently
    sending an incomplete request.
    """

    def _replace(match: re.Match[str]) -> str:
        return _lookup(match.group(1), match.group(2), args, allowed_env)

    return _TEMPLATE_PATTERN.sub(_replace, template)


def substitute_tree(value: Any, args: dict[str, Any], allowed_env: frozenset[str]) -> Any:
    """Recursively substitute templates in any JSON-shaped value.

    Strings get `substitute_string` applied; dicts and lists are walked.
    Non-string scalars (numbers, bools, None) pass through unchanged.
    """
    if isinstance(value, str):
        return substitute_string(value, args, allowed_env)
    if isinstance(value, dict):
        return {k: substitute_tree(v, args, allowed_env) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute_tree(item, args, allowed_env) for item in value]
    return value


# ---------------------------------------------------------------------------
# Response extraction (dot-path)
# ---------------------------------------------------------------------------


def extract_path(body: Any, path: str) -> Any:
    """Walk `body` along a dot-separated `path` and return the leaf value.

    Returns ``None`` if any segment is missing or the body is not a mapping
    at that point. A leading ``$.`` is accepted and stripped so configs
    written with the conventional JSONPath prefix still resolve cleanly
    against the simple dot-path walker. Anything more exotic (array
    indexing, wildcards) is intentionally unsupported in v1; document the
    limitation and revisit in a follow-up when a real config requires it.
    """
    if not path:
        return None
    if path.startswith("$."):
        path = path[2:]
    elif path == "$":
        return body

    cursor: Any = body
    for segment in path.split("."):
        if not segment:
            return None
        if isinstance(cursor, dict) and segment in cursor:
            cursor = cursor[segment]
            continue
        return None
    return cursor


def extract_response(body: Any, extract: dict[str, str]) -> dict[str, Any]:
    """Apply every ``name -> path`` mapping in ``extract`` against ``body``.

    Returns a new dict in the standardised LLM-facing shape. Missing paths
    resolve to ``None`` rather than raising so a single missing field
    cannot blow up an otherwise-successful response.
    """
    return {name: extract_path(body, path) for name, path in extract.items()}


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


def build_error(
    code: str,
    detail: str,
    error_mapping: dict[str, str] | None = None,
    status: int | None = None,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    """Build a ``ToolResult`` carrying the standardised error envelope.

    Looks the human-friendly message up in ``error_mapping`` first, falling
    back to the module-level default for ``code``. ``error_detail`` always
    carries the technical reason (exception text, status code, etc.) for
    logs and debugging without leaking it into the LLM-facing message
    unless the admin opted in via the mapping.

    ``ToolResult.error`` is kept as ``"<code>: <message>"`` so the
    orchestration layer's existing log line stays informative.
    """
    mapping = error_mapping or {}
    message = mapping.get(code) or _DEFAULT_ERROR_MESSAGES.get(code, "Tool execution failed.")
    payload: dict[str, Any] = {
        "error_code": code,
        "error_message": message,
        "error_detail": detail,
        "status": status,
    }
    if extra:
        payload.update(extra)
    return ToolResult(success=False, data=payload, error=f"{code}: {message}")


# ---------------------------------------------------------------------------
# Validation against args_schema (minimal JSON-Schema subset)
# ---------------------------------------------------------------------------


def _check_args_against_schema(args: dict[str, Any], schema: dict[str, Any]) -> None:
    """Enforce `required` + `properties.<name>.type` from `args_schema`.

    We intentionally keep this narrow rather than pulling in a full
    jsonschema validator. The schema field's primary job is to register
    the tool's arg contract with the LLM; runtime validation here just
    catches obviously-wrong calls before we send the HTTP request.
    """
    if not schema:
        return
    required = schema.get("required") or []
    if isinstance(required, list):
        for name in required:
            if not isinstance(name, str) or name not in args:
                raise GenericApiConfigError(f"required argument '{name}' is missing")
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return
    for name, prop in properties.items():
        if name not in args or not isinstance(prop, dict):
            continue
        expected_type = prop.get("type")
        value = args[name]
        if expected_type == "string" and not isinstance(value, str):
            raise GenericApiConfigError(f"argument '{name}' must be a string")
        if expected_type == "integer" and not isinstance(value, int):
            raise GenericApiConfigError(f"argument '{name}' must be an integer")
        if expected_type == "number" and not isinstance(value, int | float):
            raise GenericApiConfigError(f"argument '{name}' must be a number")
        if expected_type == "boolean" and not isinstance(value, bool):
            raise GenericApiConfigError(f"argument '{name}' must be a boolean")
        if expected_type == "object" and not isinstance(value, dict):
            raise GenericApiConfigError(f"argument '{name}' must be an object")
        if expected_type == "array" and not isinstance(value, list):
            raise GenericApiConfigError(f"argument '{name}' must be an array")


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class GenericApiTool(BaseTool):
    tool_type = ToolType.EXTERNAL_API

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Send the configured HTTP request and return the standardised result.

        Failures surface under a normalised envelope (#66 stage 5):
        ``{error_code, error_message, error_detail, status, ...}``. The
        ``error_code`` is one of the module-level ERROR_* constants so the
        LLM (and observability) can branch on a stable identifier instead
        of parsing free text. ``error_message`` is taken from
        ``config.error_mapping[code]`` when set, otherwise from the module
        default; ``error_detail`` always carries the technical reason
        (exception text, status, etc.) for logs.

        Success paths return ``{status, data, headers}`` (plus ``raw`` when
        extraction was applied) exactly as Stage 4 left them.
        """
        # Pre-parse so we can pull error_mapping even before the config is
        # fully validated. A bad config falls back to an empty mapping,
        # which just means the default human-readable message wins.
        error_mapping_raw = (
            parameters.get("error_mapping") if isinstance(parameters, dict) else None
        )
        error_mapping = error_mapping_raw if isinstance(error_mapping_raw, dict) else {}

        try:
            config = parse_config(parameters)
        except GenericApiConfigError as exc:
            return build_error(ERROR_CONFIG_INVALID, str(exc), error_mapping)

        # Once parsed, use the mapping the config explicitly carries.
        error_mapping = config.error_mapping

        args = parameters.get("args") or {}
        if not isinstance(args, dict):
            return build_error(ERROR_ARGS_INVALID, "args must be an object", error_mapping)

        try:
            _check_args_against_schema(args, config.args_schema)
        except GenericApiConfigError as exc:
            return build_error(ERROR_ARGS_INVALID, str(exc), error_mapping)

        try:
            url = substitute_string(config.url, args, config.allowed_env)
            headers = {
                str(k): str(substitute_tree(v, args, config.allowed_env))
                for k, v in config.headers.items()
            }
            query = {
                str(k): str(substitute_tree(v, args, config.allowed_env))
                for k, v in config.query.items()
            }
            body = substitute_tree(config.body, args, config.allowed_env)
        except TemplateSubstitutionError as exc:
            return build_error(ERROR_TEMPLATE_INVALID, str(exc), error_mapping)

        logger.info(
            "generic_api_request",
            method=config.method,
            url=url,
            has_body=body is not None,
            timeout_seconds=config.timeout_seconds,
        )

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.request(
                    method=config.method,
                    url=url,
                    headers=headers or None,
                    params=query or None,
                    json=body if body is not None else None,
                )
        except httpx.TimeoutException as exc:
            logger.warning(
                "generic_api_timeout",
                url=url,
                timeout_seconds=config.timeout_seconds,
                error=str(exc),
            )
            return build_error(
                ERROR_TIMEOUT,
                f"request exceeded {config.timeout_seconds}s ({exc})",
                error_mapping,
            )
        except httpx.RequestError as exc:
            # Covers ConnectError, ReadError, ConnectTimeout, DNS failures,
            # SSL errors, ... anything below the response layer. TimeoutException
            # is a subclass and already handled above, so this only fires for
            # genuine transport failures.
            logger.warning(
                "generic_api_network_error",
                url=url,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return build_error(
                ERROR_NETWORK,
                f"{type(exc).__name__}: {exc}",
                error_mapping,
            )

        # Parse the body. JSON failure is only a hard error when extraction
        # was configured (we cannot extract from non-JSON); otherwise we
        # fall back to text so plain-text endpoints still work.
        raw_body: Any
        body_was_json = True
        try:
            raw_body = response.json()
        except ValueError:
            raw_body = response.text
            body_was_json = False

        if config.extract and not body_was_json:
            logger.warning(
                "generic_api_invalid_response",
                url=url,
                status=response.status_code,
                reason="extract configured but response was not JSON",
            )
            return build_error(
                ERROR_INVALID_RESPONSE,
                "response was not JSON but extract was configured",
                error_mapping,
                status=response.status_code,
                extra={"raw": raw_body, "headers": dict(response.headers)},
            )

        success = response.status_code in config.success_statuses

        # When extract is configured, the LLM sees the standardised shape
        # (stable names defined by the admin) under `data`. The raw vendor
        # payload stays accessible under `raw` so reviewers / logs can still
        # see what the upstream actually returned. With no extract config,
        # we hand back the raw body directly to keep simple configs simple.
        if config.extract:
            data_payload: Any = extract_response(raw_body, config.extract)
            result_data: dict[str, Any] = {
                "status": response.status_code,
                "data": data_payload,
                "raw": raw_body,
                "headers": dict(response.headers),
            }
        else:
            result_data = {
                "status": response.status_code,
                "data": raw_body,
                "headers": dict(response.headers),
            }

        logger.info(
            "generic_api_response",
            url=url,
            status=response.status_code,
            success=success,
            extracted_keys=list(config.extract.keys()),
        )

        if success:
            return ToolResult(success=True, data=result_data)

        # Non-success: classify by status into a normalised code. Preserve
        # the raw body + headers alongside the error envelope so the LLM
        # (and operators) can still inspect what came back.
        if 400 <= response.status_code < 500:
            code = ERROR_HTTP_4XX
        elif 500 <= response.status_code < 600:
            code = ERROR_HTTP_5XX
        else:
            code = ERROR_HTTP_UNEXPECTED
        return build_error(
            code,
            f"upstream returned HTTP {response.status_code}",
            error_mapping,
            status=response.status_code,
            extra={
                "data": result_data["data"],
                "raw": result_data.get("raw"),
                "headers": result_data["headers"],
            },
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """Return True if `parameters` carries a parseable config and valid args.

        `parameters` is expected to carry both the tool config (under the
        standard keys: request, response, auth, error_mapping, args_schema)
        and the LLM-supplied call arguments under the `args` key. We treat
        a missing `args` as an empty dict so configs with no required
        arguments still validate cleanly.
        """
        try:
            config = parse_config(parameters)
        except GenericApiConfigError as exc:
            logger.warning("generic_api_config_invalid", error=str(exc))
            return False

        args = parameters.get("args") or {}
        if not isinstance(args, dict):
            logger.warning("generic_api_args_invalid", reason="args must be an object")
            return False

        try:
            _check_args_against_schema(args, config.args_schema)
        except GenericApiConfigError as exc:
            logger.warning("generic_api_args_invalid", error=str(exc))
            return False

        return True
