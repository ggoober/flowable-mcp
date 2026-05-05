"""Unit tests for tests/e2e/conftest.py::_build_e2e_env (TASK-006 mandatory #11 / DA #7).

Covers TC-U-18..TC-U-19. Verifies the no-mutation invariant — _build_e2e_env
must NEVER touch ``os.environ`` directly, only return a copy.
"""

from __future__ import annotations

import os

import pytest

from tests.e2e.conftest import _E2E_ENV_DEFAULTS, _build_e2e_env

pytestmark = [pytest.mark.unit]


def test_build_e2e_env_when_called_then_does_not_mutate_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure default key is absent so we'd notice if setdefault leaked.
    monkeypatch.delenv("FLOWABLE_BASE_URL", raising=False)
    snapshot = dict(os.environ)

    result = _build_e2e_env({"FLOWABLE_BASE_URL": "http://test:9999"})

    assert os.environ == snapshot, "_build_e2e_env mutated os.environ"
    assert result["FLOWABLE_BASE_URL"] == "http://test:9999"


def test_build_e2e_env_when_override_provided_then_override_wins_over_default() -> None:
    overrides = {"FLOWABLE_BASE_URL": "http://custom:9090"}

    env = _build_e2e_env(overrides)

    assert env["FLOWABLE_BASE_URL"] == "http://custom:9090"
    # Other defaults still applied
    assert env["FLOWABLE_USERNAME"] == _E2E_ENV_DEFAULTS["FLOWABLE_USERNAME"]


def test_build_e2e_env_when_no_overrides_then_defaults_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in _E2E_ENV_DEFAULTS:
        monkeypatch.delenv(key, raising=False)

    env = _build_e2e_env()

    for key, default in _E2E_ENV_DEFAULTS.items():
        assert env[key] == default
