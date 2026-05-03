# TASK-002: 11 MCP Tools — BPM Lifecycle (wave 2)

> **Шаблон M (Standard).** Полные §1–§10 обязательны. §15 — hot-path performance.

---

## §0. Meta

| Field | Value |
|-------|-------|
| **ID** | TASK-002 |
| **Type** | feature |
| **Priority** | Must |
| **Status** | draft |
| **Size** | L (300–600 строк новых + тесты) |
| **Complexity** | Standard |
| **Affected Modules** | `src/flowable_mcp/tools/process.py`, `tools/task.py`, `tools/history.py`, `tools/debug.py`, `tools/admin.py`, `client.py`, `models/` (new package), `errors.py`, `server.py`, `tests/unit/`, `tests/integration/`, `tests/e2e/` |
| **Author / Assignee** | Denis Tskhay / — |
| **Dependencies** | TASK-001 (scaffold + `list_process_definitions`) |
| **Created / Updated** | 02.05.2026 / 02.05.2026 |

---

## §1. Context & Purpose

**Проблема:** После TASK-001 в `flowable-mcp` есть только read-only tool `list_process_definitions`. MCP-клиент не может запускать процессы, работать с задачами, деплоить BPMN, получать историю — то есть не предоставляет реальной BPM-функциональности.

**Зачем:** Покрыть 6 BPM use-case'ов (process instance lifecycle, user task lifecycle, deployments, deadletter triage, historic query, event subscriptions) через 11 новых MCP tools. Пользователь Claude Code/Desktop должен получить полный BPM-контроль без curl/UI.

**Связь с проектом:** Roadmap v0.1 (process+task) — полный wave 2. Все endpoints из Flowable REST 8.0.0. Pipeline solution-search провёл Architecture Decision Phase 1 (02.05.2026) — RECOMMENDED решение F-2' (score 4.35 repaired).

---

## §2. Objective

**Цель:** Реализовать 11 новых MCP tools (+ рефактор клиента под F-2' architecture) с 6 новыми DTOs, 2 новыми классами ошибок, полным набором unit/integration/e2e тестов.

**Must-deliver:**
- `models/` package (6 DTO + `Variable`/`VariableList`); `errors.py` (+`FlowableValidationError`, +`FlowableConflictError`).
- `FlowableClient` рефактор: `__init__(http_retry, http_no_retry)` + `_call()` + `_call_multipart()` + 11 публичных методов.
- Per-module `register(mcp, client)` в `tools/process.py`, `task.py`, `history.py`, `debug.py`, `admin.py`.
- `server.py` lifespan: `AsyncExitStack`, два `AsyncClient`, loop через модули.
- Unit-тесты (≥ 3 на AC для Must-stories) с `respx` — итого 46 TC.
- Integration-тесты против Docker `flowable-rest:8.0.0` — 9 TC.
- E2E тесты (FastMCP `Client` → server → Docker) — 5 TC.
- `RESULT.md`.

**Out of scope:**
- transientVariables, startFormVariables, signalName/messageName при старте.
- Batch retry deadletter jobs.
- CMMN / DMN / Identity tools — отдельные задачи.

---

## §3. Usage Scenarios

> Истории сгенерированы story-gen pipeline (wave 2, 02.05.2026). Все 6 историй — вердикт **Go with conditions**. Полный отчёт: [`story-gen_02_05_26.md`](story-gen_02_05_26.md).

### S-1: Process Instance Lifecycle

> As a **BPM-инженер**, I want to **start a process instance by definition key/ID with variables, check its status, and cancel it — all through MCP tools**, so that **I have full lifecycle control over process instances without leaving Claude Code**.

**Priority:** Must | **Size:** M | **Score:** 4.35 (growth)
**Affected Modules:** `tools/process.py`, `client.py`, `models/`, `errors.py`, `server.py`
**New types:** `ProcessInstance` DTO, `FlowableValidationError`, `FlowableConflictError`

**Key Constraints:**
- POST `/runtime/process-instances` — `retries=0` (non-idempotent)
- XOR: `process_definition_key` ИЛИ `process_definition_id`, не оба/ни один → `ValueError` до сети
- `variables` mapping: `bool` → `"boolean"` ДО `int`-проверки (т.к. `bool is int` в Python)
- `CancelledError` во время POST — пробрасывается без подавления

AC → [§10 S-1](#s-1-process-instance-lifecycle-ac)

---

### S-2: User Task Lifecycle

> As a **BPM-инженер**, I want to **list user tasks with filters, claim/complete/delegate a task with variables and dueDate awareness**, so that **I can advance BPM processes through human-in-the-loop steps without leaving Claude Code**.

**Priority:** Must | **Size:** L | **Score:** 4.20 (growth)
**Affected Modules:** `tools/task.py`, `client.py`, `models/`, `errors.py`, `server.py`
**New types:** `Task` DTO, `FlowableConflictError` (409 на claim)

**Key Constraints:**
- `claim` на уже claimed task → Flowable 409 → `FlowableConflictError`
- `complete` — проверка `dueDate` в tool (warning в stderr, не блокирует); `datetime.now(tz=timezone.utc)`
- `list_tasks(max_results=...)` — hard limit 200, `ValueError` если >200
- Все фильтры через Flowable query params (не in-memory)

AC → [§10 S-2](#s-2-user-task-lifecycle-ac)

---

### S-3: Deployment Management

> As a **BPM-инженер / DevOps**, I want to **deploy a BPMN file (base64-encoded) to Flowable and list existing deployments with name filter**, so that **I can manage process definition versioning and CI/CD through Claude Code without curl**.

**Priority:** Should | **Size:** M | **Score:** 3.50 (growth)
**Affected Modules:** `tools/admin.py`, `client.py`, `models/`, `errors.py`, `server.py`
**New types:** `Deployment` DTO

**Key Constraints:**
- Невалидный base64 → `ValueError` до HTTP запроса
- BPMN > 5 MB → `ValueError` с сообщением о лимите
- Flowable 400 (parse error) → `FlowableValidationError` с Flowable error message
- Multipart upload через `httpx` `files=` param (отдельный `_call_multipart`)

AC → [§10 S-3](#s-3-deployment-management-ac)

---

### S-4: DeadLetter Triage

> As a **DevOps**, I want to **get a paginated list of deadletter jobs filtered by processDefinitionKey (max 200) and retry a single job by ID**, so that **I can recover from job failures without manual curl against Flowable Management API**.

**Priority:** Should | **Size:** S | **Score:** 3.90 (growth)
**Affected Modules:** `tools/debug.py`, `client.py`, `models/`, `errors.py`, `server.py`
**New types:** `DeadLetterJob` DTO

**Key Constraints:**
- `max_results` hard limit 200 — `ValueError` если >200
- Нет batch retry; только single job
- `retry_deadletter_job` POST — `retries=0`
- Flowable Management API endpoint (`/management/deadletter-jobs`) верифицируется в integration test

AC → [§10 S-4](#s-4-deadletter-triage-ac)

---

### S-5: Historic Process Instance Query

> As a **BPM-инженер**, I want to **query completed and active process instances using server-side filters (by key, businessKey, date range) with a hard max_results limit**, so that **I can verify process execution history without direct DB access**.

**Priority:** Could | **Size:** M | **Score:** 3.00 (growth)
**Affected Modules:** `tools/history.py`, `client.py`, `models/`, `errors.py`, `server.py`
**New types:** `HistoricProcessInstance` DTO

**Key Constraints:**
- `max_results` hard limit 500 — `ValueError` если >500
- Все фильтры через Flowable query params — **никакой Python-side фильтрации/сортировки/агрегации**
- Нет in-memory aggregate

AC → [§10 S-5](#s-5-historic-process-instance-query-ac)

---

### S-6: Event Subscriptions List

> As a **DevOps**, I want to **list active event subscriptions (message/signal) with filter by eventType and processDefinitionKey**, so that **I can diagnose processes waiting for events without accessing Flowable UI**.

**Priority:** Could | **Size:** S | **Score:** 3.55 (growth)
**Affected Modules:** `tools/debug.py`, `client.py`, `models/`, `errors.py`, `server.py`
**New types:** `EventSubscription` DTO

**Key Constraints:**
- Response shape `GET /runtime/event-subscriptions` верифицируется в integration test против Docker Flowable 8.0
- Если Flowable не поддерживает фильтр по `processDefinitionKey` — допустим in-tool filter при N ≤ 100

AC → [§10 S-6](#s-6-event-subscriptions-ac)

---

## §4. Architectural Constraints

> Только нестандартные ограничения. Стандартные (layered arch, async-only, stdout silent, pydantic v2, etc.) — в CLAUDE.md §1-2 и shared-standards §0-§2.

### 4.1 Структурные ограничения (F-2' solution)

| # | Constraint | Reason |
|---|-----------|--------|
| **AC-N1** | Два `AsyncClient`: `http_retry` (GET/idempotent, `retries=N`) и `http_no_retry` (POST/DELETE, `retries=0`) | POST создаёт сущности — retry на `TransportError` может создать дубли (DD-5, DD-6) |
| **AC-N2** | `FlowableClient._call(...)` — единственная точка входа для всех HTTP-вызовов | Централизует CancelledError→TransportError→status mapping; ни один метод не вызывает `client.request()` напрямую |
| **AC-N3** | Per-module `register(mcp: FastMCP, client: FlowableClient)` в каждом `tools/*.py` | Масштабируется на cmmn/dmn/identity без правки `server.py`; инжектирует клиент явно (DI) |
| **AC-N4** | `models/` — подпакет вместо монолитного `models.py` | 6+ DTO из 6 BPM-доменов; разбивка предотвращает циклические импорты при росте |
| **AC-N5** | `VariableList(RootModel[list[Variable]])` с bool-before-int validator | `bool` — подкласс `int` в Python; порядок `isinstance`-проверок критичен для типа Flowable |
| **AC-N6** | `Annotated[int, Field(le=N)]` в сигнатурах tools для hard-limit полей | pydantic валидирует до выполнения тела tool; ноль boilerplate |
| **AC-N7** | `AsyncExitStack` в `lifespan` для управления двумя `AsyncClient` | Корректный порядок teardown; устраняет post-yield nonlocal holder anti-pattern (DD-7) |

### 4.2 Cross-Cutting Fixes (CC-1..CC-7)

| # | Fix | Where |
|---|-----|-------|
| CC-1 | `AsyncExitStack` в lifespan — оба клиента закрываются через `stack.enter_async_context()` | `server.py` |
| CC-2 | Named logger `_logger = logging.getLogger(__name__)` + `AuthorizationFilter` (strip password из log records) | `server.py`, `client.py` |
| CC-3 | `_call_multipart(path, files, *, response_model)` — отдельный метод для multipart uploads | `client.py` |
| CC-4 | AST-lint pre-commit hook: запрещает `print()` и `StreamHandler(sys.stdout)` во всех `src/` | `.pre-commit-config.yaml` |
| CC-5 | CI grep-guard (СТ-3): `grep -rn "sys.stdout" src/` — fails build при нахождении | `.github/workflows/` |
| CC-6 | CI tools-set assertion: `assert frozenset(mcp.list_tools()) == EXPECTED_TOOLS` | `tests/smoke/` или `server.py` startup |
| CC-7 | `pytest-xdist -n 2` cap для integration тестов (не перегружать Docker) | `pyproject.toml` |

---

## §5. Contracts & Interfaces

### 5.1 FlowableClient — конструктор и внутренние методы

**Конструктор:**
```python
class FlowableClient:
    def __init__(
        self,
        http_retry: httpx.AsyncClient,      # idempotent requests (GET, HEAD)
        http_no_retry: httpx.AsyncClient,   # non-idempotent (POST, DELETE, PUT)
    ) -> None: ...
```

**`_call` — единственная точка HTTP-вызова (F-2' core):**
```python
async def _call(
    self,
    method: str,
    path: str,
    *,
    idempotent: bool,
    response_model: type[T] | None = None,
    expect_json: bool = True,
    **kwargs: Any,
) -> T | dict | None:
    client = self._retry if idempotent else self._no_retry
    try:
        resp = await client.request(method, path, **kwargs)
    except asyncio.CancelledError:
        raise                                                        # AC-X4: ВЫШЕ TransportError
    except httpx.TransportError as exc:
        raise FlowableConnectionError(                              # AC-X1
            f"Connection failed: {type(exc).__name__}"
        ) from exc
    if resp.status_code == 204:
        return None
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise _map_status(exc) from exc
    if not expect_json or response_model is None:
        return None
    return response_model.model_validate(resp.json())              # AC-X3: в models/ нет httpx
```

**`_call_multipart` — отдельный путь для загрузки файлов (CC-3):**
```python
async def _call_multipart(
    self,
    path: str,
    files: dict[str, Any],
    *,
    response_model: type[T] | None = None,
) -> T | None: ...
```

**`_map_status` — маппинг HTTP-статусов в typed errors:**
```python
def _map_status(exc: httpx.HTTPStatusError) -> FlowableError:
    status = exc.response.status_code
    # 400 → FlowableValidationError (с body message)
    # 401, 403 → FlowableAuthError
    # 404 → FlowableNotFoundError
    # 409 → FlowableConflictError
    # 5xx → FlowableServerError
    # else → FlowableServerError
```

### 5.2 FlowableClient — публичные методы (12 total)

```python
# Существующий (TASK-001):
async def list_process_definitions(self, *, latest: bool = True, key: str | None = None) -> list[ProcessDefinition]

# S-1: Process Instance Lifecycle
async def start_process_instance(
    self, *, process_definition_key: str | None = None,
    process_definition_id: str | None = None,
    variables: dict[str, Any] | None = None,
    business_key: str | None = None, tenant_id: str | None = None,
) -> ProcessInstance

async def get_process_instance(self, instance_id: str) -> ProcessInstance

async def cancel_process_instance(self, instance_id: str) -> None

# S-2: User Task Lifecycle
async def list_tasks(
    self, *, process_instance_id: str | None = None,
    assignee: str | None = None, candidate_group: str | None = None,
    max_results: Annotated[int, Field(le=200)] = 20,
) -> list[Task]

async def claim_task(self, task_id: str, assignee: str) -> None
async def complete_task(self, task_id: str, variables: dict[str, Any] | None = None) -> None
async def delegate_task(self, task_id: str, assignee: str) -> None

# S-3: Deployment Management
async def list_deployments(self, *, name_like: str | None = None) -> list[Deployment]
async def deploy_bpmn(self, name: str, bpmn_bytes: bytes) -> Deployment

# S-4: DeadLetter Triage
async def list_deadletter_jobs(
    self, *, process_definition_key: str | None = None,
    max_results: Annotated[int, Field(le=200)] = 50,
) -> list[DeadLetterJob]
async def retry_deadletter_job(self, job_id: str) -> None

# S-5: Historic Process Instance Query
async def list_historic_process_instances(
    self, *, process_definition_key: str | None = None,
    business_key: str | None = None,
    started_before: datetime | None = None,
    started_after: datetime | None = None,
    finished: bool | None = None,
    max_results: Annotated[int, Field(le=500)] = 100,
) -> list[HistoricProcessInstance]

# S-6: Event Subscriptions
async def list_event_subscriptions(
    self, *, event_type: str | None = None,
    process_definition_key: str | None = None,
) -> list[EventSubscription]
```

### 5.3 MCP Tool Modules — `register()` signature

```python
# tools/{process,task,history,debug,admin}.py
def register(mcp: FastMCP, client: FlowableClient) -> None:
    @mcp.tool()
    async def tool_name(..., ctx: Context) -> SomeDTO:
        ...
```

`server.py` lifespan:
```python
EXPECTED_TOOLS: frozenset[str] = frozenset({
    "list_process_definitions", "start_process_instance", "get_process_instance",
    "cancel_process_instance", "list_tasks", "claim_task", "complete_task",
    "delegate_task", "list_deployments", "deploy_bpmn", "list_deadletter_jobs",
    "retry_deadletter_job", "list_historic_process_instances", "list_event_subscriptions",
})

for mod in (process, task, history, debug, admin):
    mod.register(mcp, client)
```

### 5.4 Domain Models (DTOs) — `models/` package

```python
# models/__init__.py — re-exports all DTOs
# models/process.py
class ProcessDefinition(BaseModel): ...   # existing (moved from models.py)
class ProcessInstance(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)
    id: str
    process_definition_id: str = Field(alias="processDefinitionId")
    process_definition_key: str = Field(alias="processDefinitionKey")
    business_key: str | None = Field(default=None, alias="businessKey")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    ended: bool = False
    suspended: bool = False
    start_time: datetime | None = Field(default=None, alias="startTime")
    start_user_id: str | None = Field(default=None, alias="startUserId")

# models/task.py
class Task(BaseModel):
    id: str
    name: str | None
    assignee: str | None
    owner: str | None
    process_instance_id: str = Field(alias="processInstanceId")
    task_definition_key: str | None = Field(default=None, alias="taskDefinitionKey")
    due_date: datetime | None = Field(default=None, alias="dueDate")
    ...

# models/history.py
class HistoricProcessInstance(BaseModel):
    id: str
    process_definition_id: str = Field(alias="processDefinitionId")
    process_definition_key: str = Field(alias="processDefinitionKey")
    business_key: str | None = Field(default=None, alias="businessKey")
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    duration_in_millis: int | None = Field(default=None, alias="durationInMillis")
    start_user_id: str | None = Field(default=None, alias="startUserId")
    ended: bool = False
    deleted: bool = False

# models/deployment.py
class Deployment(BaseModel):
    id: str
    name: str
    deployment_time: datetime = Field(alias="deploymentTime")
    tenant_id: str | None = Field(default=None, alias="tenantId")

# models/deadletter.py
class DeadLetterJob(BaseModel):
    id: str
    process_instance_id: str = Field(alias="processInstanceId")
    execution_id: str = Field(alias="executionId")
    process_definition_id: str = Field(alias="processDefinitionId")
    exception_message: str | None = Field(default=None, alias="exceptionMessage")
    retries: int = 0

# models/event.py
class EventSubscription(BaseModel):
    id: str
    event_type: str = Field(alias="eventType")
    event_name: str | None = Field(default=None, alias="eventName")
    activity_id: str | None = Field(default=None, alias="activityId")
    process_instance_id: str | None = Field(default=None, alias="processInstanceId")
    process_definition_id: str | None = Field(default=None, alias="processDefinitionId")
    created: datetime | None = None

# models/variable.py
class Variable(BaseModel):
    name: str
    value: str | int | float | bool | None
    type: str  # "string" | "integer" | "double" | "boolean"

class VariableList(RootModel[list[Variable]]):
    @classmethod
    def from_python_dict(cls, d: dict[str, Any]) -> "VariableList":
        ...  # bool before int check: isinstance(v, bool) → "boolean", isinstance(v, int) → "integer"
```

### 5.5 Error Classes — добавления к `errors.py`

```python
class FlowableValidationError(FlowableError):
    """400 Bad Request — Flowable отверг payload (невалидный BPMN, некорректные данные)."""

class FlowableConflictError(FlowableError):
    """409 Conflict — конфликт состояния (claim на уже claimed task, cancel на ended instance)."""
```

### 5.6 Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| I1 | XOR: `process_definition_key` XOR `process_definition_id` | `ValueError` в tool до вызова client |
| I2 | `variables` keys — непустые строки; values — JSON-сериализуемые скаляры | `ValueError` при сборке payload |
| I3 | Все DTOs: frozen + camelCase alias + extra="ignore" | `ConfigDict(frozen=True, populate_by_name=True, extra="ignore")` |
| I4 | `bool` → `"boolean"` до `int` → `"integer"` | `isinstance(v, bool)` проверяется первым |
| I5 | stdout молчит при любом вызове любого tool | CC-4 (pre-commit AST-lint) + CC-5 (CI grep) |
| I6 | `models/` и `errors.py` не импортируют `httpx` или `fastmcp` | СТ-1 stop-point; CC-5 implicit |
| I7 | `CancelledError` пробрасывается ДО обработки `TransportError` | `_call()`: `except asyncio.CancelledError: raise` стоит первым |
| I8 | `idempotent=True` → `http_retry`; `idempotent=False` → `http_no_retry` | `_call()` client selection |
| I9 | POST/DELETE всегда вызываются с `idempotent=False` | Принудительно на каждом call-site в client |

### 5.7 Design Decisions

| # | Decision | Options Considered | Chosen | Rationale |
|---|----------|-------------------|--------|-----------|
| **DD-1** | Передача variables | A: dict-as-is; B: `[{name,value,type}]` массив | **B** | Flowable REST требует массив с типами; auto-type снимает нагрузку с клиента |
| **DD-2** | Валидация XOR key/id | A: pydantic validator; B: ручная в tool; C: в client | **B** | Application-layer ответственность; domain-модель не знает про XOR ввода |
| **DD-3** | 400 маппинг | A: `FlowableServerError`; B: `FlowableValidationError` | **B** | 400 семантически ≠ 5xx; caller должен различать «плохой запрос» и «сбой сервера» |
| **DD-4** | `None` в variables | A: omit key; B: `value: null, type: "string"` | **B** | Прозрачная семантика: «отправил None» = «None пришёл в Flowable» |
| **DD-5** | Retry для POST | A: как GET; B: retries=0 | **B** | POST не идемпотентен — retry на TransportError создаёт дубли |
| **DD-6** | Retry control | A: per-call kwarg; B: два `AsyncClient` | **B** | Per-call kwarg — human-error prone; два клиента — структурная гарантия без дисциплины |
| **DD-7** | CM vs wrapper | A: `async with` CM; B: `_call()` wrapper | **B** | async-CM post-yield holder anti-pattern; wrapper линеаризует обработку ошибок |

---

## §6. Error & Edge Case Catalog

### Happy Path (S-1 reference)

```
1. MCP client вызывает start_process_instance(process_definition_key="orderProcess",
   variables={"orderId": 123, "approved": True}, business_key="ORD-001")
2. tool: XOR-валидация key/id → OK; variables-валидация → OK
3. tool → FlowableClient.start_process_instance(...)
4. client: VariableList.from_python_dict({"orderId":123,"approved":True})
   → [{"name":"orderId","value":123,"type":"integer"},{"name":"approved","value":true,"type":"boolean"}]
5. _call("POST", "/runtime/process-instances", idempotent=False, json={...})
   → http_no_retry.request(...)
6. 201 Created → ProcessInstance.model_validate(resp.json()) → DTO
7. DTO возвращается в MCP-клиент
```

### Error / Edge Cases

| # | Trigger | Expected | Error Type |
|---|---------|----------|------------|
| E1 | Оба `key` и `id` заданы | rejected до сети | `ValueError` |
| E2 | Ни `key`, ни `id` | rejected до сети | `ValueError` |
| E3 | Flowable 404 | typed error | `FlowableNotFoundError` |
| E4 | Flowable 400 | typed error с body в message | `FlowableValidationError` |
| E5 | 401/403 | typed error без password в logs | `FlowableAuthError` |
| E6 | `TransportError` | `__cause__` set | `FlowableConnectionError` |
| E7 | 5xx | typed error | `FlowableServerError` |
| E8 | response не dict / нет `id` | typed error | `FlowableProtocolError` |
| E9 | 409 на cancel/claim | typed error | `FlowableConflictError` |
| EC1 | `variables=None` | поле опускается из body | OK |
| EC2 | `variables={}` | `variables: []` | OK (не падать) |
| EC3 | variable со значением `None` | `{value:null,type:"string"}` | OK |
| EC4 | variable с `bool` | type=`"boolean"`, не `"integer"` | OK (I4) |
| EC5 | variable с несериализуемым типом | rejected до сети | `ValueError` |
| EC6 | `business_key=""` | omit из body | OK |
| EC7 | `CancelledError` во время POST | пробрасывается | `asyncio.CancelledError` |

---

## §7. Implementation Plan

> F-2' solution: `_call` wrapper + per-module `register` + два `AsyncClient`. Один коммит после каждой фазы.

| Phase | What | Files | Depends On |
|-------|------|-------|-----------|
| **1** | `errors.py`: +`FlowableValidationError`, +`FlowableConflictError` | `errors.py` | — |
| **1** | `models/` package: 6 DTO + `Variable`/`VariableList` (с `from_python_dict`) | `models/` (new dir), `models/__init__.py`, `models/{process,task,history,deployment,deadletter,event,variable}.py` | — |
| **2** | `FlowableClient` рефактор: `__init__(http_retry, http_no_retry)`, `_call`, `_call_multipart`, `_map_status` | `client.py` | Phase 1 |
| **2** | Unit tests: `_call` matrix (11 status codes × idempotent True/False × transport error) | `tests/unit/test_client_call.py` | Phase 2 |
| **3** | `tools/process.py`: `register(mcp, client)`, tools: `start/get/cancel_process_instance` | `tools/process.py` | Phase 2 |
| **3** | `tools/task.py`: `register(mcp, client)`, tools: `list/claim/complete/delegate_task` | `tools/task.py` | Phase 2 |
| **3** | `tools/history.py`: `register(mcp, client)`, tool: `list_historic_process_instances` | `tools/history.py` | Phase 2 |
| **3** | `tools/debug.py`: `register(mcp, client)`, tools: `list_deadletter_jobs`, `retry_deadletter_job`, `list_event_subscriptions` | `tools/debug.py` | Phase 2 |
| **3** | `tools/admin.py`: `register(mcp, client)`, tools: `deploy_bpmn`, `list_deployments` | `tools/admin.py` | Phase 2 |
| **3** | Unit tests (respx): 46 TC из §9 P0+P1 | `tests/unit/` | Phase 3 |
| **4** | `server.py` lifespan: `AsyncExitStack`, два `AsyncClient`, loop `mod.register(mcp, client)`, CC-2 logging | `server.py` | Phase 3 |
| **5** | Integration tests (Docker): 9 TC | `tests/integration/` | Phase 4 |
| **6** | E2E tests (FastMCP `Client` → server → Docker): 5 TC | `tests/e2e/` | Phase 5 |

**Testability Fixes (DI — из §9 Testability Assessment):**
- `FlowableClient` получает инжектированные `http_retry`/`http_no_retry` (не создаёт AsyncClient внутри) — скрытые зависимости устранены
- Tools получают `client` через `register(mcp, client)` — нет глобального состояния, нет утечки lifespan в unit-тесты
- `_call()` тестируется через `respx_mock` без патчинга внутренностей клиента

---

## §8. Data Flow

```
MCP client (JSON-RPC 2.0 over stdio/SSE)
     │
     ▼
server.py (FastMCP, lifespan)
     │  AsyncExitStack:
     │    http_retry   = AsyncClient(transport=HTTPTransport(retries=N), limits=Limits(max_connections=10))
     │    http_no_retry = AsyncClient(limits=Limits(max_connections=10))
     │    client = FlowableClient(http_retry, http_no_retry)
     │    for mod in (process, task, history, debug, admin):
     │        mod.register(mcp, client)
     │
     ▼
tools/{domain}.py — @mcp.tool() functions (закрыто над client)
     │  per tool:
     │    • validate inputs: XOR key/id, Annotated[int, Field(le=N)] limits, variable types
     │    • client.{method}(...)
     │
     ▼
FlowableClient._call(method, path, *, idempotent, response_model, **kwargs)
     │  client = http_retry if idempotent else http_no_retry   # I8
     │  try:
     │    resp = await client.request(method, path, **kwargs)
     │  except CancelledError: raise                           # I7 / AC-X4
     │  except TransportError: → FlowableConnectionError       # AC-X1
     │  204 → None
     │  raise_for_status() except HTTPStatusError → _map_status() → typed error
     │  response_model.model_validate(resp.json())             # AC-X3
     │
     ▼
flowable-rest:8080 (Docker, Flowable 8.0.0)
```

**Variables flow (tool → Flowable):**
```
tool dict[str, Any]
  → VariableList.from_python_dict(d)
  → [Variable(name=k, value=v, type=_infer_type(v)) for k,v in d.items()]
     _infer_type: bool→"boolean" (first), int→"integer", float→"double",
                  str→"string", None→"string" (value=null)
  → JSON: [{"name":"x","value":1,"type":"integer"}, ...]
  → POST body "variables" array
```

**Error propagation:**
```
httpx.TransportError          → FlowableConnectionError  (with __cause__)
HTTPStatusError(400)          → FlowableValidationError   (body message extracted)
HTTPStatusError(401/403)      → FlowableAuthError
HTTPStatusError(404)          → FlowableNotFoundError
HTTPStatusError(409)          → FlowableConflictError
HTTPStatusError(5xx)          → FlowableServerError
Malformed JSON / missing id   → FlowableProtocolError     (from model_validate)
asyncio.CancelledError        → propagated as-is          (never swallowed)
```

**Idempotency routing:**
```
GET  list_process_definitions      idempotent=True  → http_retry
GET  get_process_instance          idempotent=True  → http_retry
GET  list_tasks                    idempotent=True  → http_retry
GET  list_deadletter_jobs          idempotent=True  → http_retry
GET  list_historic_process_instances idempotent=True → http_retry
GET  list_event_subscriptions      idempotent=True  → http_retry
GET  list_deployments              idempotent=True  → http_retry

POST start_process_instance        idempotent=False → http_no_retry
POST cancel_process_instance       idempotent=False → http_no_retry
POST claim_task                    idempotent=False → http_no_retry
POST complete_task                 idempotent=False → http_no_retry
POST delegate_task                 idempotent=False → http_no_retry
POST deploy_bpmn (multipart)       idempotent=False → http_no_retry (_call_multipart)
POST retry_deadletter_job          idempotent=False → http_no_retry
```

---

## §9. Testing Requirements

> Источник: `test-design_02_05_26.md` (Surface Analysis 15 линз, Stage 0 Regression Map, Innovation Stage 2B).
> Минимумы: [shared-standards §9.1](../../../.claude/agents/shared-standards.md#91-pyramid-и-минимумы): ≥3 unit (happy + edge + error) + ≥1 integration на AC для Must-stories.

### 9.1 Test Structure (Pyramid)

| Уровень | Файлы | Доля | Минимум на AC | Doubles |
|---------|-------|------|---------------|---------|
| Unit | `tests/unit/` | 60–70% | ≥3 (happy + edge + error) | `respx_mock`, реальный `FlowableClient`, `monkeypatch` env |
| Integration | `tests/integration/` | 20–30% | ≥1 (Must stories S-1, S-2) | Docker `flowable-rest:8.0.0`, **zero mocks** [СТ-6] |
| E2E | `tests/e2e/` | 5–10% | critical paths (S-1, S-2) | FastMCP `Client` → `python -m flowable_mcp` → Docker |

**Запуск:**
```bash
pytest tests/unit/ -m unit
pytest tests/integration/ -m integration
pytest tests/e2e/ -m e2e
```

### 9.2 Test Doubles Policy

| Уровень | Разрешено | Запрещено |
|---------|-----------|-----------|
| Unit | `respx_mock` (HTTP), `monkeypatch` (env vars), `capsys`/`caplog`, `freezegun` (datetime), `hypothesis` | Mock domain классов, mock `FlowableClient` |
| Integration | Ничего | **Любые mocks Flowable REST API** [СТ-6] |
| E2E | Ничего | Любые mocks |

**Именование:** `test_<unit>_when_<condition>_then_<result>` ([shared-standards §9.2](../../../.claude/agents/shared-standards.md))

### 9.3 Must-Test Scenarios

_Полная Decision Table: 60 TC из `test-design_02_05_26.md`._

#### P0 — Critical (обязательны до merge)

| TC-ID | Story | Tool | Condition | Expected | Pyramid |
|-------|-------|------|-----------|----------|---------|
| TC-001 | S-1 | `start_process_instance` | valid key, no variables | 201 → `ProcessInstance(status="active")` | unit |
| TC-002 | S-1 | `start_process_instance` | invalid key format → 400 | `FlowableValidationError` (`raise from exc`) | unit |
| TC-003 | S-1 | `start_process_instance` | non-existent key → 404 | `FlowableNotFoundError` | unit |
| TC-005 | S-1 | `start_process_instance` | `ConnectError` on POST | `FlowableConnectionError`; `route.call_count == 1` (retries=0) | unit |
| TC-006 | S-1 | `get_process_instance` | valid id → 200 | `ProcessInstance` DTO | unit |
| TC-007 | S-1 | `cancel_process_instance` | active id → 204 | `None`; `resp.json()` NOT called | unit |
| TC-008 | S-1 | `cancel_process_instance` | already-ended → 409 | `FlowableConflictError` | unit |
| TC-009 | S-1 | `cancel_process_instance` | non-existent → 404 | `FlowableNotFoundError` | unit |
| TC-010 | S-1 | start / get / cancel | 401 wrong password | `FlowableAuthError` | unit |
| TC-011 | S-1 | start / get / cancel | 401 + `caplog` | password NOT in any log record | unit |
| TC-012 | S-1 | `ProcessInstance` DTO | Hypothesis round-trip | `model_validate(dump(by_alias=True)) == original` | unit |
| TC-013 | S-1 | `start_process_instance` | `variables={"x": 1, "y": "s"}` | body has `[{name, value, type}]` format | unit |
| TC-015 | S-2 | `list_tasks` | `max_results=201` | `len(result) ≤ 200` | unit |
| TC-017 | S-2 | `claim_task` | already claimed → 409 | `FlowableConflictError` | unit |
| TC-018 | S-2 | `claim_task` | 200 success | `None`; body `{"action":"claim","assignee":…}` verified | unit |
| TC-019 | S-2 | `complete_task` | 400 invalid variable | `FlowableValidationError` | unit |
| TC-020 | S-2 | `complete_task` | 204 No Content | `None`; `resp.json()` NOT called | unit |
| TC-021 | S-2 | `complete_task` | dueDate compare | `datetime.now(tz=timezone.utc)` used (aware, never naive) | unit |
| TC-022 | S-2 | `delegate_task` | 200 success | body `{"action":"delegate","assignee":…}` verified | unit |
| TC-023 | S-2 | claim / complete / delegate | `ConnectError` | `call_count == 1` each (retries=0) | unit |
| TC-024 | S-2 | `Task` DTO | Hypothesis aliases | round-trip `processInstanceId`, `dueDate`, `taskDefinitionKey` | unit |
| TC-029 | S-3 | `deploy_bpmn` | invalid XML → 400 | `FlowableValidationError` | unit |
| TC-032 | S-4 | `list_deadletter_jobs` | `max_results=201` | `len ≤ 200` | unit |
| TC-034 | S-4 | `DeadLetterJob` DTO | Hypothesis aliases | `processInstanceId`, `exceptionMessage`, `executionId` | unit |
| TC-035 | S-4 | `retry_deadletter_job` | 200 OK | `None`; body `{"action":"move"}` verified (Flowable 8.0 REST moves job back to execution queue; "execute" was spec error) | unit |
| TC-036 | S-4 | `retry_deadletter_job` | 204 No Content | `None`; `resp.json()` NOT called | unit |
| TC-037 | S-4 | `retry_deadletter_job` | non-existent → 404 | `FlowableNotFoundError` | unit |
| TC-039 | S-4 | `retry_deadletter_job` | `ConnectError` | `call_count == 1` (retries=0) | unit |
| TC-041 | S-5 | `list_historic_process_instances` | `max_results=501` | `len ≤ 500` | unit |
| TC-042 | S-5 | `list_historic_process_instances` | `max_results` ∈ {0, 1, 500} | exact `len` per value | unit |
| TC-043 | S-5 | `list_historic_process_instances` | filters (`finished`, `key`) | query params correct; no in-memory filter | unit |
| TC-044 | S-5 | `HistoricProcessInstance` DTO | Hypothesis nullable fields | `startTime`, `endTime`, `deleteReason` nullable OK | unit |
| TC-046 | S-6 | `EventSubscription` DTO | Hypothesis aliases | `eventType`, `eventName`, `executionId`, `processInstanceId`, `activityId` | unit |
| TC-047 | S-1 | start → get → cancel lifecycle | real Docker | start 201 → get 200 → cancel 204 → get 404 | integration |
| TC-048 | S-2 | claim → complete | real Docker | unclaimed → claim → completed | integration |
| TC-049 | S-1 | cancel idempotency | real Docker | cancel ok → 2nd cancel → 409 | integration |
| TC-050 | S-1 | variables round-trip | real Docker | `start_process(vars)` → get → vars present | integration |
| TC-053 | S-2 | concurrent claim race | `asyncio.gather` × 2 | 1 success + 1 `FlowableConflictError` | integration |
| TC-054 | S-1 | auth fail | wrong `FLOWABLE_PASSWORD` env | `FlowableAuthError`; password NOT in `caplog` | integration |
| TC-056 | S-1 | `start_process_instance` | FastMCP MCP roundtrip | `ProcessInstance` JSON; `is_error=False` | e2e |
| TC-058 | S-2 | list → claim → complete | E2E via MCP | claim + complete succeed; 0 MCP errors | e2e |

#### P1 — High Priority

| TC-ID | Story | Tool | Condition | Expected | Pyramid |
|-------|-------|------|-----------|----------|---------|
| TC-004 | S-1 | `start_process_instance` | 5xx server error | `FlowableServerError` | unit |
| TC-014 | S-1 | `start_process_instance` | `variables={}` | body `variables: []`; no exception | unit |
| TC-016 | S-2 | `list_tasks` | empty `data` array | `[]`; no exception | unit |
| TC-025 | S-2 | `list_tasks` | filters (`process_instance_id`, `assignee`, `candidate_group`) | query params correct | unit |
| TC-026 | S-2 | `list_tasks` | `total=null` in response | fallback `len(data)`; no infinite loop | unit |
| TC-027 | S-2 | `claim_task` | non-existent → 404 | `FlowableNotFoundError` | unit |
| TC-028 | S-3 | `deploy_bpmn` | valid XML bytes | 201 → `Deployment` DTO; multipart field `"file"` | unit |
| TC-031 | S-3 | `Deployment` DTO | Hypothesis `deploymentTime` alias | round-trip OK | unit |
| TC-033 | S-4 | `list_deadletter_jobs` | filters | query params correct | unit |
| TC-038 | S-4 | `retry_deadletter_job` | 503 server error | `FlowableServerError` | unit |
| TC-040 | S-4 | `list_deadletter_jobs` | `data` missing/null | `FlowableProtocolError` | unit |
| TC-045 | S-6 | `list_event_subscriptions` | filters (`process_instance_id`, `event_type`) | query params correct | unit |
| TC-051 | S-2 | `list_tasks` subset | `list_tasks(pid) ⊆ list_tasks()` | metamorphic invariant | integration |
| TC-052 | S-3 | deploy → list | `count(N1)` → deploy → `count(N2) = N1+1` | metamorphic | integration |
| TC-055 | S-5 | `list_historic` ordering | real Docker records | Flowable order preserved; no Python sort | integration |
| TC-057 | S-1 | `cancel_process_instance` | MCP roundtrip | null result; `is_error=False` | e2e |
| TC-059 | S-2 | `complete_task` with variables | E2E | DTO serialization survives MCP boundary | e2e |

#### P2 — Normal

| TC-ID | Story | Tool | Condition | Expected | Pyramid |
|-------|-------|------|-----------|----------|---------|
| TC-030 | S-3 | `list_deployments` | 200, empty data | `[]` | unit |
| TC-060 | S-1 | `start_process_instance` | E2E invalid key | MCP error envelope with `FlowableValidationError` tag | e2e |

**Total: 60 TC.** Unit=46 (76.7%) / Integration=9 (15.0%) / E2E=5 (8.3%).

### 9.4 E2E Test Scenarios

_Fixtures: `mcp_client` (FastMCP `Client`) + `e2e_deployed_process`. Все сценарии — `@pytest.mark.e2e`._

| # | Scenario | Preconditions | Steps | Expected Outcome | Assertions |
|---|----------|---------------|-------|-----------------|------------|
| 1 | **Happy path: start process instance** (TC-056) | `flowable-rest:8.0.0` запущен; BPMN `hello-world` задеплоен через `e2e_deployed_process` | `await mcp_client.call_tool("start_process_instance", {"process_definition_key": "hello-world"})` | MCP ответ без `isError`; тело содержит `ProcessInstance` JSON с непустым `id`, `ended=false` | `assert not result.is_error`; `result_data["id"] != ""`; `result_data["ended"] == False` |
| 2 | **Error path: invalid key → MCP error envelope** (TC-060) | `flowable-rest:8.0.0` запущен | `await mcp_client.call_tool("start_process_instance", {"process_definition_key": "no-such-xyzzy"}, raise_on_error=False)` | MCP `isError=True`; пароль **не** в ответе | `assert result.is_error`; `FLOWABLE_PASSWORD_VALUE not in error_text` |
| 3 | **Edge case: double cancel → FlowableConflictError** (TC-049 E2E) | instance запущен через `e2e_deployed_process` | start → cancel1 → cancel2 (`raise_on_error=False`) | cancel1: `is_error=False`; cancel2: `isError=True` + `FlowableConflictError` | `assert not cancel1.is_error`; `assert cancel2.is_error` |
| 4 | **Task lifecycle: claim + complete roundtrip** (TC-058) | process с user task запущен (`e2e_process_with_task`) | `list_tasks(pid)` → `claim_task(id)` → `complete_task(id, vars)` | Все три: `is_error=False`; после complete задача отсутствует в `list_tasks(pid)` | все `assert not *.is_error`; повторный `list_tasks` пуст |
| 5 | **Flowable down — server survives two calls** (E2E-B1) | `FLOWABLE_BASE_URL=http://127.0.0.1:19999` (closed port) | два последовательных `start_process_instance` | оба `isError=True`; MCP server не упал | `assert result.is_error`; `"FlowableConnectionError" in error_text` |

---

## §10. Acceptance Criteria

> Мастер-список AC для всех историй TASK-002 (S-1…S-6). Краткие AC-C1…AC-C4 (Code Quality) — обязательны для **каждой** истории.

---

### S-1: Process Instance Lifecycle AC

- [ ] **AC-1:** Given валидный `process_definition_key` deployed BPMN, When `start_process_instance(key, variables={"x": 1})`, Then возвращается `ProcessInstance` с непустым `id`, `ended=False`.
- [ ] **AC-2:** Given оба `key` и `id` (или ни одного), When `start_process_instance`, Then `ValueError` **до** сетевого вызова.
- [ ] **AC-3:** Given variables `{"flag": True, "n": 1, "s": "x", "f": 1.5, "z": None}`, When client формирует payload, Then типы: `boolean`, `integer`, `string`, `double`, `string` (None); `bool` не маппируется в `integer`.
- [ ] **AC-4:** Given Flowable 404, When `get_process_instance(id)` с несуществующим id, Then `FlowableNotFoundError`.
- [ ] **AC-5:** Given активный instance, When `cancel_process_instance(id)`, Then instance удалён (Flowable 204); `resp.json()` **не вызывается** для 204 No Content.
- [ ] **AC-6:** Given Flowable 400 при start с невалидными данными, Then `FlowableValidationError` (не `FlowableServerError`).
- [ ] **AC-7:** Given `variables` содержит несериализуемый объект (e.g. `set()`), When `start_process_instance`, Then `ValueError` до сетевого запроса.
- [ ] **AC-8:** Given `CancelledError` во время POST `/runtime/process-instances`, Then пробрасывается без подавления; POST **не ретраится** (`retries=0`).
- [ ] **AC-9:** _(Surface: S1-ST-01, Risk=9)_ Given `cancel_process_instance(id)` вызывается повторно на уже завершённом instance, Then `FlowableConflictError` (Flowable 409).
- [ ] **AC-10:** _(Surface: S8-EP-07, Risk=9)_ Given неверные credentials (401/403) на любом из трёх методов, Then `FlowableAuthError`; password и username **не** фигурируют в `args[0]` и в `caplog` records.
- [ ] **AC-11:** _(Surface: S14-BC-01, Risk=9)_ Given Flowable возвращает `ProcessInstance` с неизвестными полями, Then DTO успешно разбирается; неизвестные поля отброшены (`extra="ignore"`).
- [ ] **AC-12:** _(Surface: BUG-05)_ Given `get_process_instance(id)` получает ответ 200, Then тело разбирается как **единичный JSON-объект** (не `{data: [...]}` обёртка).

---

### S-2: User Task Lifecycle AC

- [ ] **AC-1:** Given активный process instance с user task, When `list_tasks(process_instance_id=id)`, Then возвращается список `Task` DTO с корректными полями.
- [ ] **AC-2:** Given unclaimed task, When `claim_task(task_id, user_id)`, Then task `assignee = user_id`.
- [ ] **AC-3:** Given уже claimed task, When `claim_task` другим user, Then `FlowableConflictError` (Flowable 409).
- [ ] **AC-4:** Given claimed task, When `complete_task(task_id, variables={"approved": True})`, Then task завершается, process продвигается.
- [ ] **AC-5:** Given task с `dueDate` в прошлом, When `complete_task`, Then warning логируется в stderr (не блокирует выполнение).
- [ ] **AC-6:** Given claimed task, When `delegate_task(task_id, target_user_id)`, Then task делегирована.
- [ ] **AC-7:** `list_tasks(max_results=201)` → `ValueError` до сетевого вызова.
- [ ] **AC-8:** `dueDate` comparison использует `datetime.now(tz=timezone.utc)`, не naive datetime.
- [ ] **AC-9:** _(Surface: S7-CT-02, Risk=9)_ `complete_task` и `claim_task`, возвращающие 204 No Content, возвращают `None`; `resp.json()` **не вызывается** для 204-ответов.
- [ ] **AC-10:** _(Surface: BUG-07)_ Given `list_tasks` получает ответ без поля `total` или с нечисловым `total`, Then fallback `len(data)`; бесконечного цикла нет.
- [ ] **AC-11:** _(Surface: S2-BV-01, Risk=9)_ `list_tasks(max_results=0)` → `[]`; `list_tasks(max_results=1)` → `len(result) ≤ 1`.

---

### S-3: Deployment Management AC

- [ ] **AC-1:** Given валидный base64-encoded BPMN файл ≤ 5 MB, When `deploy_process(name, bpmn_base64)`, Then возвращается `Deployment` DTO с непустым `id` и `deploy_time`.
- [ ] **AC-2:** Given невалидный base64, When `deploy_process`, Then `ValueError` до HTTP запроса.
- [ ] **AC-3:** Given BPMN > 5 MB, When `deploy_process`, Then `ValueError` с сообщением о превышении лимита.
- [ ] **AC-4:** When `list_deployments(name_like="order%")`, Then возвращается список `Deployment` DTO с фильтрацией по имени.
- [ ] **AC-5:** Given Flowable 400 (BPMN parse error), Then `FlowableValidationError` с Flowable error message.
- [ ] **AC-6:** _(Surface: S10-RL-01, Risk=9)_ `deploy_bpmn` POST выполняется с `retries=0`; при `ConnectError` — ровно 1 HTTP-запрос (`route.call_count == 1`).

---

### S-4: DeadLetter Triage AC

- [ ] **AC-1:** When `list_deadletter_jobs(max_results=50)`, Then возвращается список `DeadLetterJob` DTO (не более 50 items).
- [ ] **AC-2:** Given `max_results > 200`, When `list_deadletter_jobs`, Then `ValueError` до сетевого вызова.
- [ ] **AC-3:** When `list_deadletter_jobs(process_definition_key="orderProcess")`, Then фильтр передаётся как Flowable query param (не in-memory).
- [ ] **AC-4:** Given существующий deadletter job, When `retry_deadletter_job(job_id)`, Then job переносится в execution queue (Flowable 200/204).
- [ ] **AC-5:** Given несуществующий job, When `retry_deadletter_job(job_id)`, Then `FlowableNotFoundError`.
- [ ] **AC-6:** `retry_deadletter_job` POST не ретраится (`retries=0`).
- [ ] **AC-7:** _(Surface: S7-CT-02, Risk=9)_ `retry_deadletter_job`, получающий 204 No Content, возвращает `None`; `resp.json()` **не вызывается**.
- [ ] **AC-8:** _(Surface: BUG-07)_ Given `list_deadletter_jobs` без поля `total`, Then fallback `len(data)`; бесконечного цикла нет.

---

### S-5: Historic Process Instance Query AC

- [ ] **AC-1:** When `list_historic_process_instances(process_definition_key="order", max_results=100)`, Then возвращается список `HistoricProcessInstance` DTO с server-side фильтрацией.
- [ ] **AC-2:** Given `max_results > 500`, When `list_historic_process_instances`, Then `ValueError` до сетевого вызова.
- [ ] **AC-3:** Все фильтры передаются как Flowable query params — **никакой Python-side фильтрации/сортировки/агрегации**.
- [ ] **AC-4:** DTO содержит поля: `id`, `process_definition_id`, `process_definition_key`, `business_key`, `start_time`, `end_time`, `duration_in_millis`, `start_user_id`, `ended`, `deleted`.
- [ ] **AC-5:** _(Surface: S2-BV-01, Risk=9)_ `max_results=0` → `[]`; `max_results=500` → OK; `max_results=501` → `ValueError`.
- [ ] **AC-6:** _(Surface: S14-BC-02, Risk=6)_ Порядок результатов — как у Flowable, без Python-сортировки.

---

### S-6: Event Subscriptions AC

- [ ] **AC-1:** When `list_event_subscriptions()`, Then возвращается список `EventSubscription` DTO.
- [ ] **AC-2:** When `list_event_subscriptions(event_type="message")`, Then фильтр применяется (через Flowable query param если поддерживается, иначе in-tool при N ≤ 100).
- [ ] **AC-3:** DTO содержит: `id`, `event_type`, `event_name`, `activity_id`, `process_instance_id`, `process_definition_id`, `created`.
- [ ] **AC-4:** Integration test верифицирует response shape `GET /runtime/event-subscriptions` против реального Docker Flowable 8.0.
- [ ] **AC-5:** _(Surface: S14-BC-01, Risk=9)_ `EventSubscription` DTO имеет `extra="ignore"`: неизвестные поля не вызывают `ValidationError`.

---

### Cross-Cutting AC (все 11 инструментов + 6 DTOs)

- [ ] **AC-X1:** `httpx.TransportError` и все его подклассы маппируются в `FlowableConnectionError` с `__cause__` set; ни один не пробрасывается как httpx-тип наружу.
- [ ] **AC-X2:** `stdout` молчит при любом вызове любого из 11 инструментов и при любом исходе. Ни `print()`, ни `logging.StreamHandler(sys.stdout)`.
- [ ] **AC-X3:** `models/` и `errors.py` не импортируют `httpx` или `fastmcp` после добавления 6 новых DTO и 2 новых классов ошибок.
- [ ] **AC-X4:** `asyncio.CancelledError` пробрасывается без подавления во всех 11 новых async-методах. `except asyncio.CancelledError: raise` стоит ДО `except httpx.TransportError`.

---

### Code Quality (обязательно для каждой истории)

- [ ] **AC-C1:** [shared-standards §1, §2](../../../.claude/agents/shared-standards.md) compliance — СТ-1…СТ-8 без нарушений.
- [ ] **AC-C2:** Coverage ≥ 80 % для нового кода (`pytest --cov`).
- [ ] **AC-C3:** `ruff check` + `mypy` зелёные.
- [ ] **AC-C4:** pydantic v2 API only — `.model_dump()`, `.model_validate()`, `.model_dump_json()`; нет `.dict()`, `.parse_obj()`, `.parse_raw()`.

---

## §15. Performance Budgets

> Hot paths затронуты: `start_process_instance` (S-1, каждый BPM-сценарий начинается здесь) и `complete_task` + `list_tasks` (S-2, human-in-the-loop цикл).

| Budget | Value | Basis |
|--------|-------|-------|
| p95 latency tool call | < 500 ms | Включает Flowable roundtrip; не включает Flowable processing time |
| MCP server startup (first tools/list) | < 2 s | AsyncExitStack + два AsyncClient creation; lifespan не делает HTTP |
| RSS idle | < 150 MB | 2 × `Limits(max_connections=10, max_keepalive_connections=5)` = 20 max sockets |
| Concurrent tool calls | ≥ 8 | 20 total connections / ~2.5 per active call = достаточный headroom |
| Unit test suite | < 10 s | pytest-asyncio, 46 TC; respx не делает реальных HTTP |
| Integration test suite | < 5 min | pytest-xdist `-n 2` cap (CC-7) против Docker |

**Two-client memory model:** два `AsyncClient` с `Limits(max_connections=10)` каждый = 20 max + 10 keepalive сокетов суммарно. При 8 одновременных tool-вызовах RSS остаётся в пределах 150 MB budget.

**Startup invariant:** `lifespan` создаёт клиентов и регистрирует tools без HTTP-запросов к Flowable — startup latency не зависит от доступности Flowable.

---

## §16. Spec Amendments (§0.1 Feedback Loop)

| Amendment | Date | Reason | Change |
|-----------|------|--------|--------|
| TC-035 action | 2026-05-02 | Flowable 8.0 REST deadletter endpoint принимает `{"action":"move"}` для перемещения job обратно в execution queue. `{"action":"execute"}` — ошибка в исходном spec (не имеет аналога в REST API 8.0). Root cause: spec написан по устаревшей документации Flowable 6.x. | TC-035 обновлён: `{"action":"execute"}` → `{"action":"move"}`. Тест TC-086 (unit) верифицирует `move`. |
