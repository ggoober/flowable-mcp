"""Typed error hierarchy for Flowable MCP.

Domain-only module: no httpx, no fastmcp imports allowed (Invariant I2, СТ-1).
"""


class FlowableError(Exception):
    """Base class for all Flowable errors."""


class FlowableConnectionError(FlowableError):
    """Flowable unreachable: ConnectError or timeout after all retries."""


class FlowableAuthError(FlowableError):
    """401/403 from Flowable. Never includes credentials in message."""


class FlowableServerError(FlowableError):
    """5xx response from Flowable."""


class FlowableNotFoundError(FlowableError):
    """404 from Flowable."""


class FlowableProtocolError(FlowableError):
    """Malformed or unexpected response structure from Flowable (AC-Λ6)."""


class FlowableValidationError(FlowableError):
    """400 Bad Request — Flowable отверг payload (невалидный BPMN, некорректные данные)."""


class FlowableConflictError(FlowableError):
    """409 Conflict — конфликт состояния (claim на уже claimed task, cancel на ended instance)."""


class FlowableDiagramError(FlowableError):
    """PNG validation failure: content-type / magic bytes / size / empty body.

    No httpx/fastmcp imports — Domain чист (СТ-1, AC-C1).
    """
