"""Shared helpers for E2E tests.

Two layers:

* ``extract_single`` / ``extract_list`` — for in-process ``Client(mcp)`` results
  (FastMCP ``CallToolResult`` objects).
* ``assert_image_content`` / ``parse_text_json`` / ``is_error_envelope`` /
  ``extract_first_content_block`` / ``extract_text_payload`` — for raw JSON-RPC
  responses returned by the subprocess harness (TASK-006 §12 mandatory #6).
"""

from __future__ import annotations

import base64
import json
from typing import Any


_PNG_MAGIC = b"\x89PNG"
_SVG_PREFIXES = (b"<?xml", b"<svg")


def extract_single(result: Any) -> dict:
    """Extract a single object from a CallToolResult."""
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return dict(structured["result"])
    if isinstance(structured, dict):
        return structured

    data = getattr(result, "data", None)
    if data is not None and hasattr(data, "model_dump"):
        return data.model_dump(by_alias=True)
    if isinstance(data, dict):
        return data

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise AssertionError(f"Could not extract single object from result: {result!r}")


def extract_list(result: Any) -> list[dict]:
    """Extract a list of objects from a CallToolResult."""
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return list(structured["result"])
    if isinstance(structured, list):
        return structured

    data = getattr(result, "data", None)
    if isinstance(data, list):
        return [
            item.model_dump(by_alias=True) if hasattr(item, "model_dump") else item
            for item in data
        ]

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "result" in parsed:
                return list(parsed["result"])
    raise AssertionError(f"Could not extract list from result: {result!r}")


# ---------------------------------------------------------------------------
# Wire-format validators for subprocess JSON-RPC responses (TASK-006).
# ---------------------------------------------------------------------------


def extract_first_content_block(rpc_response: dict[str, Any]) -> dict[str, Any]:
    """Return ``result.content[0]`` from a JSON-RPC ``tools/call`` response.

    Raises ``AssertionError`` with a helpful message if the envelope is malformed.
    """
    assert "result" in rpc_response, (
        f"JSON-RPC response missing 'result' (error envelope?): {rpc_response!r}"
    )
    result = rpc_response["result"]
    content = result.get("content") if isinstance(result, dict) else None
    assert isinstance(content, list) and content, (
        f"Expected non-empty result.content list, got: {result!r}"
    )
    block = content[0]
    assert isinstance(block, dict), f"content[0] is not a dict: {block!r}"
    return block


def assert_image_content(
    rpc_response: dict[str, Any],
    *,
    mime_prefix: str,
    min_bytes: int = 100,
) -> bytes:
    """Assert ``result.content[0]`` is a valid MCP ImageContent block.

    Validates: ``type=='image'``, ``mimeType`` startswith ``mime_prefix``, base64
    data decodes to bytes whose magic header matches the expected MIME family
    (PNG → ``\\x89PNG``, SVG → ``<?xml``/``<svg``). Returns decoded bytes.
    """
    block = extract_first_content_block(rpc_response)
    assert block.get("type") == "image", (
        f"Expected ImageContent, got type={block.get('type')!r}: {block!r}"
    )
    mime = block.get("mimeType", "")
    assert isinstance(mime, str) and mime.startswith(mime_prefix), (
        f"Unexpected mimeType: {mime!r} (expected prefix {mime_prefix!r})"
    )
    data = block.get("data")
    assert isinstance(data, str) and data, f"ImageContent.data must be non-empty str: {data!r}"
    decoded = base64.b64decode(data, validate=True)
    assert len(decoded) >= min_bytes, (
        f"Image payload too small ({len(decoded)} bytes < {min_bytes}); likely empty"
    )
    if mime_prefix.endswith("png"):
        assert decoded[:4] == _PNG_MAGIC, f"PNG magic bytes missing: {decoded[:8]!r}"
    elif mime_prefix.endswith("svg+xml"):
        head = decoded.lstrip()[:32]
        assert any(head.startswith(p) for p in _SVG_PREFIXES), (
            f"SVG prelude missing: {head!r}"
        )
    return decoded


def extract_text_payload(rpc_response: dict[str, Any]) -> str:
    """Return concatenated TextContent payload from a JSON-RPC ``tools/call`` response."""
    assert "result" in rpc_response, (
        f"JSON-RPC response missing 'result': {rpc_response!r}"
    )
    content = rpc_response["result"].get("content", [])
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def parse_text_json(rpc_response: dict[str, Any]) -> Any:
    """For tools that return a JSON dict serialised in TextContent (e.g. source bundle)."""
    raw = extract_text_payload(rpc_response)
    if not raw:
        return None
    return json.loads(raw)


def is_error_envelope(rpc_response: dict[str, Any]) -> bool:
    """True if response is a JSON-RPC error envelope OR a successful call with ``isError=True``."""
    if "error" in rpc_response:
        return True
    result = rpc_response.get("result")
    return isinstance(result, dict) and bool(result.get("isError", False))
