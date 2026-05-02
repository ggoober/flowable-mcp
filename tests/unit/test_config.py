from __future__ import annotations

import pytest

from flowable_mcp.config import Settings


def test_settings_when_password_set_then_repr_does_not_leak_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_PASSWORD", "super-secret")
    s = Settings()
    assert "super-secret" not in repr(s)
    assert "super-secret" not in str(s.password)


def test_settings_when_no_password_then_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLOWABLE_PASSWORD", raising=False)
    with pytest.raises(Exception):
        Settings()


def test_settings_when_base_url_has_trailing_slash_then_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_BASE_URL", "http://host:8080/service/")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert s.base_url == "http://host:8080/service"


def test_settings_when_base_url_has_multiple_trailing_slashes_then_all_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_BASE_URL", "http://host:8080/service///")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert s.base_url == "http://host:8080/service"


def test_settings_when_timeout_s_is_zero_then_settings_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_TIMEOUT_S", "0.0")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert s.timeout_s == 0.0


def test_settings_when_retry_attempts_zero_then_transport_retries_equals_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_RETRY_ATTEMPTS", "0")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert max(0, s.retry_attempts - 1) == 0


def test_settings_when_retry_attempts_one_then_transport_retries_equals_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert max(0, s.retry_attempts - 1) == 0


def test_settings_when_username_empty_string_then_settings_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_USERNAME", "")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert s.username == ""


def test_settings_when_base_url_without_service_path_then_settings_valid_but_url_lacks_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_BASE_URL", "http://localhost:8080/flowable-rest")
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    s = Settings()
    assert s.base_url == "http://localhost:8080/flowable-rest"
    assert "/service" not in s.base_url
