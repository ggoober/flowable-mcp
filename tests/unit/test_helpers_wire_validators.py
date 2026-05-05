"""Unit tests for tests/e2e/_helpers.py wire-format validators (TASK-006 M6 / F-QA-1).

Covers TC-U-01..TC-U-07 from test-scenarios_05_05_26.md.
Pure unit: synthetic dict envelopes, no network, no subprocess.
"""

from __future__ import annotations

import base64

import pytest

from tests.e2e._helpers import (
    assert_image_content,
    extract_first_content_block,
    extract_text_payload,
    is_error_envelope,
    parse_text_json,
)

pytestmark = [pytest.mark.unit]


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _wrap_image(data: bytes, mime: str = "image/png") -> dict:
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "result": {
            "content": [
                {"type": "image", "mimeType": mime, "data": encoded},
            ]
        }
    }


# ---------------------------------------------------------------------------
# extract_first_content_block (TC-U-01..03)
# ---------------------------------------------------------------------------


def test_extract_first_content_block_when_envelope_valid_then_returns_block_dict() -> None:
    resp = {"result": {"content": [{"type": "text", "text": "hello"}]}}

    block = extract_first_content_block(resp)

    assert block == {"type": "text", "text": "hello"}


def test_extract_first_content_block_when_result_missing_then_raises_assertion() -> None:
    resp = {"id": 1, "jsonrpc": "2.0"}

    with pytest.raises(AssertionError, match="missing 'result'"):
        extract_first_content_block(resp)


def test_extract_first_content_block_when_content_empty_then_raises_assertion() -> None:
    resp = {"result": {"content": []}}

    with pytest.raises(AssertionError, match="non-empty"):
        extract_first_content_block(resp)


# ---------------------------------------------------------------------------
# assert_image_content (TC-U-04..06)
# ---------------------------------------------------------------------------


def test_assert_image_content_when_valid_png_then_returns_decoded_bytes() -> None:
    payload = _PNG_MAGIC + b"\x00" * 200  # >= default min_bytes=100
    resp = _wrap_image(payload)

    decoded = assert_image_content(resp, mime_prefix="image/png", min_bytes=100)

    assert decoded[:4] == b"\x89PNG"
    assert len(decoded) == len(payload)


def test_assert_image_content_when_type_is_text_then_raises_assertion() -> None:
    resp = {
        "result": {
            "content": [
                {"type": "text", "text": "not-an-image"},
            ]
        }
    }

    with pytest.raises(AssertionError, match="Expected ImageContent"):
        assert_image_content(resp, mime_prefix="image/png")


def test_assert_image_content_when_payload_too_small_then_raises_assertion() -> None:
    resp = _wrap_image(_PNG_MAGIC)  # only 8 bytes

    with pytest.raises(AssertionError, match="too small"):
        assert_image_content(resp, mime_prefix="image/png", min_bytes=100)


# ---------------------------------------------------------------------------
# is_error_envelope (TC-U-07)
# ---------------------------------------------------------------------------


def test_is_error_envelope_when_error_key_present_then_returns_true() -> None:
    assert is_error_envelope({"error": {"code": -32600, "message": "Invalid"}}) is True


def test_is_error_envelope_when_result_is_error_flag_then_returns_true() -> None:
    assert is_error_envelope({"result": {"isError": True, "content": []}}) is True


def test_is_error_envelope_when_normal_result_then_returns_false() -> None:
    assert is_error_envelope({"result": {"content": [{"type": "text", "text": "ok"}]}}) is False


# ---------------------------------------------------------------------------
# extract_text_payload + parse_text_json (extra invariants)
# ---------------------------------------------------------------------------


def test_extract_text_payload_when_multiple_text_blocks_then_joined_with_newline() -> None:
    resp = {
        "result": {
            "content": [
                {"type": "text", "text": "line1"},
                {"type": "image", "mimeType": "image/png", "data": "ZmFrZQ=="},
                {"type": "text", "text": "line2"},
            ]
        }
    }

    assert extract_text_payload(resp) == "line1\nline2"


def test_parse_text_json_when_payload_empty_then_returns_none() -> None:
    resp = {"result": {"content": []}}

    assert parse_text_json(resp) is None


def test_parse_text_json_when_payload_is_json_object_then_returns_dict() -> None:
    resp = {
        "result": {
            "content": [
                {"type": "text", "text": '{"definition_id": "abc", "model": null}'},
            ]
        }
    }

    parsed = parse_text_json(resp)

    assert parsed == {"definition_id": "abc", "model": None}
