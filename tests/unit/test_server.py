from __future__ import annotations

import logging
import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableAuthError
from flowable_mcp.server import lifespan, setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    orig_handlers = list(root.handlers)
    orig_level = root.level
    yield
    root.handlers.clear()
    root.handlers.extend(orig_handlers)
    root.setLevel(orig_level)


# ---------------------------------------------------------------------------
# TC-20
# ---------------------------------------------------------------------------

def test_tool_list_when_any_response_then_stdout_is_clean(capsys):
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging()

    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# TC-36
# ---------------------------------------------------------------------------

def test_server_when_logging_configured_then_handler_uses_stderr_not_stdout():
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging()

    assert len(root.handlers) >= 1
    for handler in root.handlers:
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is not sys.stdout
    assert not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
        for h in root.handlers
    )


# ---------------------------------------------------------------------------
# TC-37
# ---------------------------------------------------------------------------

def test_server_when_started_then_no_stdout_handler_in_root_logger():
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging()

    assert not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
        for h in root.handlers
    )


# ---------------------------------------------------------------------------
# TC-56
# ---------------------------------------------------------------------------

def test_setup_logging_when_called_twice_then_no_duplicate_handler():
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging()
    setup_logging()

    assert len(root.handlers) == 1


# ---------------------------------------------------------------------------
# TC-57
# ---------------------------------------------------------------------------

def test_setup_logging_when_stdout_handler_exists_then_raises_runtime_error():
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.StreamHandler(sys.stdout))

    with pytest.raises(RuntimeError, match="stdout log handler detected"):
        setup_logging()


# ---------------------------------------------------------------------------
# TC-58
# ---------------------------------------------------------------------------

def test_setup_logging_when_called_twice_stdout_check_runs_both_times():
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging()

    root.addHandler(logging.StreamHandler(sys.stdout))

    with pytest.raises(RuntimeError, match="stdout log handler detected"):
        setup_logging()


# ---------------------------------------------------------------------------
# TC-59
# ---------------------------------------------------------------------------

def test_setup_logging_when_file_handler_present_then_no_runtime_error():
    root = logging.getLogger()
    root.handlers.clear()

    fh = logging.FileHandler(os.devnull)
    root.addHandler(fh)

    try:
        setup_logging()
    except RuntimeError:
        pytest.fail("setup_logging raised RuntimeError unexpectedly with a FileHandler present")
    finally:
        fh.close()


# ---------------------------------------------------------------------------
# TC-60
# ---------------------------------------------------------------------------

def test_setup_logging_when_stderr_handler_present_then_no_runtime_error():
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.StreamHandler(sys.stderr))

    try:
        setup_logging()
    except RuntimeError:
        pytest.fail("setup_logging raised RuntimeError unexpectedly with a stderr StreamHandler")


# ---------------------------------------------------------------------------
# TC-79
# ---------------------------------------------------------------------------

async def test_lifespan_when_exception_in_yield_then_aclose_still_called(monkeypatch):
    monkeypatch.setenv("FLOWABLE_PASSWORD", "test")

    aclose_count = 0

    async def counting_aclose(self):
        nonlocal aclose_count
        aclose_count += 1
        self._closed = True

    with patch.object(FlowableClient, "aclose", counting_aclose):
        with pytest.raises(RuntimeError, match="lifespan error"):
            async with lifespan(MagicMock()) as _ctx:
                raise RuntimeError("lifespan error")

    assert aclose_count == 1


# ---------------------------------------------------------------------------
# TC-80
# ---------------------------------------------------------------------------

async def test_client_list_when_response_ok_then_log_record_has_method_path_status_latency(
    flowable_client: FlowableClient,
    respx_mock,
    caplog: pytest.LogCaptureFixture,
):
    PD_URL = "http://flowable-test/repository/process-definitions"
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    with caplog.at_level(logging.INFO, logger="flowable_mcp.client"):
        await flowable_client.list_process_definitions()

    records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(records) == 1
    r = records[0]
    assert r.__dict__["method"] == "GET"
    assert r.__dict__["path"] == "/repository/process-definitions"
    assert r.__dict__["status"] == 200
    assert r.__dict__["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# TC-81
# ---------------------------------------------------------------------------

async def test_client_list_when_401_then_log_record_has_latency_ms_before_error(
    flowable_client: FlowableClient,
    respx_mock,
    caplog: pytest.LogCaptureFixture,
):
    PD_URL = "http://flowable-test/repository/process-definitions"
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(401))

    with caplog.at_level(logging.INFO, logger="flowable_mcp.client"):
        with pytest.raises(FlowableAuthError):
            await flowable_client.list_process_definitions()

    records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(records) == 1
    r = records[0]
    assert r.__dict__["status"] == 401
    assert r.__dict__["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# TC-82
# ---------------------------------------------------------------------------

async def test_client_list_when_401_then_log_record_does_not_contain_password(
    flowable_client: FlowableClient,
    respx_mock,
    caplog: pytest.LogCaptureFixture,
):
    PD_URL = "http://flowable-test/repository/process-definitions"
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(401))

    with caplog.at_level(logging.DEBUG, logger="flowable_mcp.client"):
        with pytest.raises(FlowableAuthError):
            await flowable_client.list_process_definitions()

    secret = "test-pass"
    for record in caplog.records:
        assert secret not in record.getMessage()
        assert secret not in str(record.__dict__)
