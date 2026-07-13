"""POST /v1/tools/try: run an external_api tool config once for testing (#229).

Lets the config UI fire a tool's configured HTTP request with user-supplied
args and show the live response, without going through a conversation or the
LLM. It reuses the exact production adapter (``GenericApiTool.execute``) so
what you test is what the agent will actually run.

Because it triggers a live server-side request to a user-supplied URL and
hands the raw response back to the browser, it is deliberately fenced:
- an SSRF guard (``assert_public_url``) blocks internal / metadata targets,
- the request timeout is clamped, and
- the response payload returned to the browser is size-capped.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from taskorbit.api.deps import get_current_user_id
from taskorbit.logging.setup import get_logger
from taskorbit.tools.generic_api import GenericApiTool, assert_public_url

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/tools", tags=["tools"])

_MAX_TIMEOUT_SECONDS = 15.0
_MAX_RESPONSE_BYTES = 256 * 1024


class ToolTryRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    args: dict[str, Any] = Field(default_factory=dict)


class ToolTryResponse(BaseModel):
    success: bool
    elapsed_ms: int
    data: dict[str, Any]


def _clamp_timeout(parameters: dict[str, Any]) -> dict[str, Any]:
    """Cap request.timeout_seconds so a Try-it call cannot hold a worker open.

    Only clamps a present, numeric value that exceeds the ceiling. Absent or
    malformed values are left for ``parse_config`` to default or reject.
    """
    request = parameters.get("request")
    if not isinstance(request, dict) or "timeout_seconds" not in request:
        return parameters
    try:
        configured = float(request["timeout_seconds"])
    except (TypeError, ValueError):
        return parameters
    if configured <= _MAX_TIMEOUT_SECONDS:
        return parameters
    return {
        **parameters,
        "request": {**request, "timeout_seconds": _MAX_TIMEOUT_SECONDS},
    }


def _strip_env_access(parameters: dict[str, Any]) -> dict[str, Any]:
    """Force auth.allowed_env to empty on an untrusted inline config.

    Try-it runs a config straight from the request body. Since the config
    also carries its own {{env.X}} whitelist (auth.allowed_env), a caller
    could otherwise whitelist any server env var (API keys, DATABASE_URL,
    the GCP service-account material) and exfiltrate it by templating it
    into a request to a public URL they control. Clearing the whitelist
    makes any {{env.X}} reference fail as TEMPLATE_INVALID instead of
    resolving. Args still work; a tool that genuinely needs an env secret
    is verified through real dispatch with its stored, admin-approved
    whitelist, not through Try-it.
    """
    return {**parameters, "auth": {"allowed_env": []}}


def _cap_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Replace an oversized response payload with a small notice."""
    if len(json.dumps(data, default=str).encode("utf-8")) <= _MAX_RESPONSE_BYTES:
        return data
    return {
        "truncated": True,
        "error_detail": f"Response exceeded {_MAX_RESPONSE_BYTES} bytes and was omitted.",
        "status": data.get("status"),
    }


@router.post("/try", response_model=ToolTryResponse)
async def try_tool(
    request: ToolTryRequest,
    _user_id: int = Depends(get_current_user_id),  # noqa: B008
) -> ToolTryResponse:
    """Execute one external_api request and return the standardised envelope."""
    parameters = _strip_env_access(_clamp_timeout(dict(request.parameters)))
    execute_params = {**parameters, "args": request.args}

    start = time.perf_counter()
    result = await GenericApiTool().execute(execute_params, url_guard=assert_public_url)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    logger.info("tool_try", success=result.success, elapsed_ms=elapsed_ms)
    return ToolTryResponse(
        success=result.success,
        elapsed_ms=elapsed_ms,
        data=_cap_payload(result.data),
    )
