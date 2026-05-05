"""Unit tests for tests/e2e/conftest.py::_post_with_retry (TASK-006 M6 / F-QA-3).

Covers TC-U-13..TC-U-17. Uses respx for HTTP mocking — allowed at unit level
per shared-standards §9.3 (СТ-6 forbids mocks only in tests/integration/ and
tests/e2e/).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.e2e.conftest import _post_with_retry

pytestmark = [pytest.mark.unit]

_URL = "http://flowable.test/repository/deployments"
_FILES = {"file": ("x.bpmn20.xml", b"<x/>", "application/xml")}


@pytest.fixture(autouse=True)
def _disable_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real backoff to keep tests fast (logic doesn't depend on duration)."""

    async def _instant(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("tests.e2e.conftest.asyncio.sleep", _instant)


# ---------------------------------------------------------------------------
# TC-U-13..TC-U-17
# ---------------------------------------------------------------------------


async def test_post_with_retry_when_first_attempt_succeeds_then_returns_response() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_URL).mock(
            return_value=httpx.Response(201, json={"id": "dep-1"})
        )
        async with httpx.AsyncClient() as client:
            resp = await _post_with_retry(client, _URL, files=_FILES)

    assert resp.status_code == 201
    assert route.call_count == 1


async def test_post_with_retry_when_5xx_twice_then_succeeds_on_third() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(201, json={"id": "dep-1"}),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await _post_with_retry(client, _URL, files=_FILES, attempts=3)

    assert resp.status_code == 201
    assert route.call_count == 3


async def test_post_with_retry_when_connect_error_then_retries_and_succeeds() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_URL).mock(
            side_effect=[
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                httpx.Response(201, json={"id": "dep-1"}),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await _post_with_retry(client, _URL, files=_FILES, attempts=3)

    assert resp.status_code == 201
    assert route.call_count == 3


async def test_post_with_retry_when_4xx_then_raises_immediately_without_retry() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_URL).mock(return_value=httpx.Response(400))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await _post_with_retry(client, _URL, files=_FILES, attempts=3)

    # 4xx is permanent — no retry.
    assert route.call_count == 1


async def test_post_with_retry_when_all_attempts_5xx_then_raises_http_status_error() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_URL).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await _post_with_retry(client, _URL, files=_FILES, attempts=3)

    assert route.call_count == 3
