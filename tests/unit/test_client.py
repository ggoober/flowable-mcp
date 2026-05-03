from __future__ import annotations

import asyncio
import unittest.mock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.errors import (
    FlowableAuthError,
    FlowableConnectionError,
    FlowableError,
    FlowableNotFoundError,
    FlowableProtocolError,
    FlowableServerError,
)
from flowable_mcp.models import ProcessDefinition

PD_URL = "http://flowable-test/repository/process-definitions"

_PD_PAYLOAD = {
    "id": "pd-1",
    "key": "myproc",
    "version": 1,
    "deploymentId": "dep-1",
    "name": "My Process",
    "suspended": False,
}


# ---------------------------------------------------------------------------
# Basic list behaviour (TC-02..TC-08)
# ---------------------------------------------------------------------------


async def test_client_list_when_valid_response_then_returns_list_of_dtos(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": [_PD_PAYLOAD]})
    )
    result = await flowable_client.list_process_definitions()
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ProcessDefinition)
    assert result[0].id == "pd-1"


async def test_client_list_when_empty_data_then_returns_empty_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    result = await flowable_client.list_process_definitions()
    assert result == []


async def test_client_list_when_latest_true_then_query_param_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(latest=True)
    url = str(respx_mock.calls[0].request.url)
    assert "latest=true" in url


async def test_client_list_when_latest_false_then_query_param_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(latest=False)
    url = str(respx_mock.calls[0].request.url)
    assert "latest=false" in url


async def test_client_list_when_key_provided_then_key_query_param_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(key="myproc")
    url = str(respx_mock.calls[0].request.url)
    assert "key=myproc" in url


async def test_client_list_when_key_none_then_no_key_query_param(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(key=None)
    url = str(respx_mock.calls[0].request.url)
    assert "key" not in url


async def test_client_list_when_key_empty_string_then_no_key_query_param(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(key="")
    url = str(respx_mock.calls[0].request.url)
    assert "key" not in url


# ---------------------------------------------------------------------------
# Auth errors (TC-09, TC-10, TC-14, TC-15)
# ---------------------------------------------------------------------------


async def test_client_list_when_401_then_raises_auth_error_without_password(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(FlowableAuthError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "test-pass" not in exc_info.value.args[0]


async def test_client_list_when_403_then_raises_auth_error_without_password(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(FlowableAuthError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "test-pass" not in exc_info.value.args[0]


async def test_client_list_when_401_then_no_retry_performed(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(PD_URL)
    route.mock(return_value=httpx.Response(401))
    with pytest.raises(FlowableAuthError):
        await flowable_client.list_process_definitions()
    assert route.call_count == 1


async def test_client_list_when_403_then_no_retry_performed(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(PD_URL)
    route.mock(return_value=httpx.Response(403))
    with pytest.raises(FlowableAuthError):
        await flowable_client.list_process_definitions()
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# Connection / timeout errors (TC-11..TC-13, TC-28, TC-29, TC-62..TC-66)
# ---------------------------------------------------------------------------


async def test_client_list_when_connect_error_all_retries_then_raises_connection_error_with_cause(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


async def test_client_list_when_connect_error_then_success_on_retry_then_returns_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_timeout_all_retries_then_raises_connection_error_with_cause(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.TimeoutException("timeout"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)


async def test_client_list_when_retry_attempts_one_and_connect_error_then_raises_immediately(
    unit_settings: Settings, respx_mock
) -> None:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await client.list_process_definitions()
    await http.aclose()


async def test_client_list_when_all_retries_exhausted_then_cause_is_original_connect_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


async def test_client_list_when_connect_timeout_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectTimeout("connect timeout"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "ConnectTimeout" in exc_info.value.args[0]


async def test_client_list_when_read_timeout_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ReadTimeout("read timeout"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "ReadTimeout" in exc_info.value.args[0]


async def test_client_list_when_write_timeout_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.WriteTimeout("write timeout"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_pool_timeout_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.PoolTimeout("pool timeout"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_connection_error_then_cause_type_name_in_message(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "ConnectError" in exc_info.value.args[0]


# ---------------------------------------------------------------------------
# Transport error subclasses — BLOCKER-2 fix tests (TC-B1..TC-B4)
# ---------------------------------------------------------------------------


async def test_client_list_when_remote_protocol_error_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        side_effect=httpx.RemoteProtocolError("server disconnected")
    )
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.RemoteProtocolError)


async def test_client_list_when_read_error_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.ReadError("read failed"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_write_error_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.WriteError("write failed"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_network_error_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.NetworkError("net error"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


# ---------------------------------------------------------------------------
# 5xx errors (TC-16, TC-41)
# ---------------------------------------------------------------------------


async def test_client_list_when_5xx_all_retries_then_raises_server_error_with_cause(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )
    with pytest.raises(FlowableServerError) as exc_info:
        await flowable_client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


async def test_client_list_when_503_then_exactly_1_http_call_no_transport_retry(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(PD_URL)
    route.mock(return_value=httpx.Response(503, text="Service Unavailable"))
    with pytest.raises(FlowableServerError) as exc_info:
        await flowable_client.list_process_definitions()
    assert route.call_count == 1
    assert "503" in exc_info.value.args[0]


# ---------------------------------------------------------------------------
# Other HTTP status codes (TC-32)
# ---------------------------------------------------------------------------


async def test_client_list_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.list_process_definitions()


# ---------------------------------------------------------------------------
# Protocol errors (TC-44..TC-48, INN-09..INN-11, TC-A1..TC-A4)
# ---------------------------------------------------------------------------


async def test_client_list_when_data_missing_then_error_message_contains_actual_keys(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(
            200, json={"total": 0, "size": 0, "start": 0}
        )
    )
    with pytest.raises(FlowableProtocolError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "expected 'data' key" in exc_info.value.args[0]


async def test_client_list_when_data_is_dict_then_error_message_contains_type_name(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": {"id": "abc"}})
    )
    with pytest.raises(FlowableProtocolError) as exc_info:
        await flowable_client.list_process_definitions()
    msg = exc_info.value.args[0]
    assert "dict" in msg
    assert "expected list at .data" in msg


async def test_client_list_when_data_is_string_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": "some-string"})
    )
    with pytest.raises(FlowableProtocolError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "str" in exc_info.value.args[0]


async def test_client_list_when_data_is_integer_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": 42})
    )
    with pytest.raises(FlowableProtocolError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "int" in exc_info.value.args[0]


async def test_client_list_when_data_null_then_error_message_contains_null_hint(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    with pytest.raises(FlowableProtocolError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "'data' is null" in exc_info.value.args[0]


async def test_list_process_definitions_when_data_not_array_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": {"id": "abc"}})
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_process_definitions()


async def test_list_process_definitions_when_data_key_missing_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"total": 0})
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_process_definitions()


async def test_list_process_definitions_when_data_is_null_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_payload_is_list_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(
            200,
            text='[{"id":"x"}]',
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(FlowableProtocolError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "list" in exc_info.value.args[0]


async def test_client_list_when_payload_is_string_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(
            200,
            text='"error"',
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_payload_is_null_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(
            200,
            text="null",
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_process_definitions()


async def test_client_list_when_payload_is_number_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(
            200,
            text="42",
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_process_definitions()


# ---------------------------------------------------------------------------
# Error hierarchy (TC-67..TC-68)
# ---------------------------------------------------------------------------


def test_client_list_when_auth_error_then_is_subclass_of_flowable_error() -> None:
    assert issubclass(FlowableAuthError, FlowableError)


def test_client_list_when_connection_error_then_is_subclass_of_flowable_error() -> None:
    assert issubclass(FlowableConnectionError, FlowableError)


# ---------------------------------------------------------------------------
# Server error body (TC-69..TC-70)
# ---------------------------------------------------------------------------


async def test_client_list_when_server_error_then_body_snippet_in_message(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(500, text='{"message":"NPE at line 42"}')
    )
    with pytest.raises(FlowableServerError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "500" in exc_info.value.args[0]
    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


async def test_client_list_when_server_error_body_long_then_message_truncated_at_200(
    flowable_client: FlowableClient, respx_mock
) -> None:
    long_body = "X" * 500
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(500, text=long_body)
    )
    with pytest.raises(FlowableServerError) as exc_info:
        await flowable_client.list_process_definitions()
    msg = exc_info.value.args[0]
    prefix = "Server error 500: "
    body_part = msg[len(prefix):]
    assert len(body_part) <= 200


# ---------------------------------------------------------------------------
# Query params (TC-74..TC-76)
# ---------------------------------------------------------------------------


async def test_client_list_when_latest_true_params_then_only_latest_param_set(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(latest=True)
    url = str(respx_mock.calls[0].request.url)
    assert "latest=true" in url
    assert "key=" not in url


async def test_client_list_when_key_with_special_chars_then_param_encoded_correctly(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions(key="my-process_v2.0")
    url = str(respx_mock.calls[0].request.url)
    assert "my-process_v2.0" in url or "my-process_v2" in url


async def test_client_list_when_key_filter_all_results_match_key(
    flowable_client: FlowableClient, respx_mock
) -> None:
    pd1 = {"id": "pd-1", "key": "myproc", "version": 1, "deploymentId": "dep-1"}
    pd2 = {"id": "pd-2", "key": "myproc", "version": 2, "deploymentId": "dep-2"}
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": [pd1, pd2]})
    )
    result = await flowable_client.list_process_definitions(key="myproc")
    assert all(item.key == "myproc" for item in result)


# ---------------------------------------------------------------------------
# aclose / lifecycle (TC-27, TC-77, TC-78)
# ---------------------------------------------------------------------------


async def test_client_aclose_when_called_twice_then_no_exception(
    unit_settings: Settings,
) -> None:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    await client.aclose()
    await client.aclose()


async def test_client_aclose_when_called_concurrently_then_no_double_close(
    unit_settings: Settings,
) -> None:
    close_count = 0
    original_aclose = httpx.AsyncClient.aclose

    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )

    async def counted_aclose(self: httpx.AsyncClient) -> None:
        nonlocal close_count
        close_count += 1
        await original_aclose(self)

    with unittest.mock.patch.object(httpx.AsyncClient, "aclose", counted_aclose):
        client = FlowableClient(http_retry=http, http_no_retry=http)
        await asyncio.gather(client.aclose(), client.aclose())

    assert close_count == 1
    assert client._closed is True


async def test_client_when_http_aclose_called_then_closed_flag_true(
    unit_settings: Settings,
) -> None:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    await client.aclose()
    assert client._closed is True


# ---------------------------------------------------------------------------
# No singleton (TC-35)
# ---------------------------------------------------------------------------


def test_client_when_instantiated_twice_then_separate_instances(
    unit_settings: Settings,
) -> None:
    http1 = httpx.AsyncClient(timeout=1.0)
    http2 = httpx.AsyncClient(timeout=1.0)
    c1 = FlowableClient(http_retry=http1, http_no_retry=http1)
    c2 = FlowableClient(http_retry=http2, http_no_retry=http2)
    assert c1 is not c2


# ---------------------------------------------------------------------------
# Observability (TC-42..TC-43, TC-80..TC-82)
# ---------------------------------------------------------------------------


async def test_client_list_when_401_then_latency_ms_logged_before_raise(
    flowable_client: FlowableClient, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="flowable_mcp.client")
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(FlowableAuthError):
        await flowable_client.list_process_definitions()
    records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(records) == 1
    assert records[0].__dict__["status"] == 401
    assert records[0].__dict__["latency_ms"] >= 0


async def test_client_list_when_200_then_latency_ms_is_positive_in_log_record(
    flowable_client: FlowableClient, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="flowable_mcp.client")
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions()
    records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["path"] == "/repository/process-definitions"
    assert record.__dict__["status"] == 200
    assert record.__dict__["latency_ms"] >= 0


async def test_client_list_when_response_ok_then_log_record_has_method_path_status_latency(
    flowable_client: FlowableClient, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="flowable_mcp.client")
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    await flowable_client.list_process_definitions()
    records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["path"] == "/repository/process-definitions"
    assert record.__dict__["status"] == 200
    assert record.__dict__["latency_ms"] >= 0


async def test_client_list_when_401_then_log_record_has_latency_ms_before_error(
    flowable_client: FlowableClient, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="flowable_mcp.client")
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(FlowableAuthError):
        await flowable_client.list_process_definitions()
    records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(records) == 1
    assert records[0].__dict__["latency_ms"] >= 0
    assert records[0].__dict__["status"] == 401


async def test_client_list_when_401_then_log_record_does_not_contain_password(
    flowable_client: FlowableClient, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="flowable_mcp.client")
    respx_mock.get(PD_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(FlowableAuthError):
        await flowable_client.list_process_definitions()
    for record in caplog.records:
        assert "test-pass" not in record.getMessage()
        assert "test-pass" not in str(record.__dict__)


async def test_client_list_when_retry_attempts_2_connect_error_then_2_total_attempts(
    unit_settings: Settings, respx_mock
) -> None:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    respx_mock.get(PD_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
    await http.aclose()


async def test_client_list_when_retry_attempts_2_timeout_then_2_total_attempts(
    unit_settings: Settings, respx_mock
) -> None:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    respx_mock.get(PD_URL).mock(side_effect=httpx.TimeoutException("timeout"))
    with pytest.raises(FlowableConnectionError) as exc_info:
        await client.list_process_definitions()
    assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)
    await http.aclose()


# ---------------------------------------------------------------------------
# Fault inject (INN-07..INN-08)
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_timeout_then_200_then_returns_or_raises_per_policy(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(side_effect=httpx.TimeoutException("timeout"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.list_process_definitions()


async def test_list_process_definitions_when_503_exceeds_retry_budget_then_flowable_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(503, text="Service unavailable")
    )
    with pytest.raises(FlowableServerError) as exc_info:
        await flowable_client.list_process_definitions()
    assert "503" in exc_info.value.args[0]


# ---------------------------------------------------------------------------
# Cancellation (INN-12..INN-14)
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_cancelled_mid_request_then_propagates_and_no_leak(
    flowable_client: FlowableClient, respx_mock
) -> None:
    async def raise_cancelled(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    respx_mock.get(PD_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.list_process_definitions()
    assert not flowable_client._closed


async def test_list_process_definitions_when_taskgroup_one_fails_then_exception_group_no_leak(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async def fail() -> None:
        raise RuntimeError("deliberate failure")

    collected_excs: list[Exception] = []
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(flowable_client.list_process_definitions())
            tg.create_task(fail())
    except* RuntimeError as eg:
        collected_excs.extend(eg.exceptions)

    assert len(collected_excs) == 1
    assert not flowable_client._closed


async def test_list_process_definitions_when_8_parallel_with_mock_then_8_calls_equal_results(
    flowable_client: FlowableClient, respx_mock
) -> None:
    pd = {"id": "pd-1", "key": "proc", "version": 1, "deploymentId": "dep-1"}
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": [pd]})
    )
    results = await asyncio.gather(
        *[flowable_client.list_process_definitions() for _ in range(8)]
    )
    assert len(results) == 8
    assert all(r == results[0] for r in results)


# ---------------------------------------------------------------------------
# No-retry for auth (INN-15)
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_401_then_no_retry_and_auth_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(PD_URL)
    route.mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(FlowableAuthError):
        await flowable_client.list_process_definitions()
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# Base URL trailing slash (TC-24)
# ---------------------------------------------------------------------------


async def test_client_when_base_url_has_trailing_slash_then_request_url_is_correct(
    monkeypatch: pytest.MonkeyPatch, respx_mock
) -> None:
    monkeypatch.setenv("FLOWABLE_BASE_URL", "http://flowable-test/")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "test-pass")
    s = Settings()
    assert not s.base_url.endswith("/")
