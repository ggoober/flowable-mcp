# flowable-mcp

MCP server для Flowable BPM Engine 8.x.

Тонкая обёртка над Flowable REST API, превращающая операции движка в MCP-tools для использования в Claude Code / Claude Desktop / других MCP-клиентах.

## Статус

Pre-alpha. Базовый CRUD по процессам, тасками, истории, deployments и debug-операциям работает (24 MCP-tool'а, покрыто unit + integration + e2e тестами на реальном Docker Flowable).

## Стек

- Python 3.12+
- FastMCP (stdio transport)
- httpx (async)
- pydantic v2

## Целевой Flowable

`flowable/flowable-rest:8.0.0` (Docker)

## Доступные tools

| Группа | Tools |
|--------|-------|
| **Process** | `list_process_definitions`, `start_process_instance`, `get_process_instance`, `cancel_process_instance`, `list_process_instances`, `get_process_variables`, `set_process_variable`, `suspend_process_definition`, `activate_process_definition`, `suspend_process_instance`, `activate_process_instance` |
| **Task** | `list_tasks`, `claim_task`, `complete_task`, `delegate_task` |
| **History** | `list_historic_process_instances`, `list_historic_task_instances` |
| **Debug** | `list_deadletter_jobs`, `retry_deadletter_job`, `list_event_subscriptions` |
| **Admin** | `list_deployments`, `deploy_bpmn`, `delete_deployment` |

## Quick start

```bash
# 1. Поднять Flowable + Postgres
docker compose -f docker/flowable/compose.yml up -d

# 2. Установить зависимости (пример с uv)
uv sync

# 3. Задать пароль и запустить сервер вручную (для отладки)
export FLOWABLE_PASSWORD=test
uv run flowable-mcp
```

Подробная инструкция по подключению к Claude Code / Claude Desktop, переменные окружения, troubleshooting — в [RUNBOOK.md](RUNBOOK.md).

## Тесты

- **unit** (`tests/unit/`) — без сети, `respx` мок'и httpx;
- **integration** (`tests/integration/`) — реальный flowable-rest через `docker/flowable/compose.yml`;
- **e2e** (`tests/e2e/`) — MCP-клиент → сервер → Flowable.

```bash
uv run pytest tests/unit            # быстро, без Docker
uv run pytest tests/integration     # требует поднятый compose
uv run pytest tests/e2e             # требует поднятый compose
```

## Лицензия

MIT (TBD)
