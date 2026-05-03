"""Shared helpers for E2E tests — extract single/list payloads from CallToolResult."""

from __future__ import annotations

import json
from typing import Any


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
