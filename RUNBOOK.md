# flowable-mcp — Runbook

Подключение MCP-сервера `flowable-mcp` к MCP-клиенту (Claude Code / Claude Desktop) и работа с Flowable BPM Engine.

---

## 1. Предусловия

- Установлены **Docker Desktop** (или Docker Engine + compose v2) и **Python 3.12+**.
- Менеджер пакетов: рекомендуется [`uv`](https://docs.astral.sh/uv/) (поддерживается lock-файл `uv.lock`). Альтернатива — `pip` с venv.
- Свободен порт **8080** (Flowable REST).

## 2. Поднять Flowable

Compose-файл проекта поднимает Postgres + `flowable-rest:8.0.0` с дефолтными creds `rest-admin / test`:

```bash
docker compose -f docker/flowable/compose.yml up -d
```

Дождаться готовности (healthcheck закладывает `start_period: 60s`):

```bash
docker compose -f docker/flowable/compose.yml ps
# флаг healthy у flowable-rest = готов
```

Smoke-проверка:

```bash
curl -u rest-admin:test http://localhost:8080/flowable-rest/service/management/engine
# {"name":"Flowable BPM Engine", ...}
```

Остановка:

```bash
docker compose -f docker/flowable/compose.yml down            # сохранить данные
docker compose -f docker/flowable/compose.yml down -v         # удалить том Postgres
```

## 3. Установить flowable-mcp

```bash
uv sync                       # создаёт .venv и устанавливает зависимости из uv.lock
```

Или классически:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -e .
```

После установки доступны два эквивалентных entry point:

- консольный скрипт `flowable-mcp`
- модульный запуск `python -m flowable_mcp`

## 4. Конфигурация (env)

Все переменные читаются с префиксом `FLOWABLE_` (см. `src/flowable_mcp/config.py`):

| Переменная | Значение по умолчанию | Описание |
|------------|----------------------|----------|
| `FLOWABLE_BASE_URL` | `http://localhost:8080/flowable-rest/service` | Base URL Flowable REST. Trailing slash снимается автоматически. |
| `FLOWABLE_USERNAME` | `rest-admin` | Basic auth user. |
| `FLOWABLE_PASSWORD` | **обязательна** | Basic auth password. |
| `FLOWABLE_TIMEOUT_S` | `10.0` | Таймаут одного HTTP-запроса. |
| `FLOWABLE_RETRY_ATTEMPTS` | `2` | Общее число попыток (1 = без ретраев). |

Для compose из `docker/flowable/compose.yml`: `FLOWABLE_PASSWORD=test`.

`.env` в корне проекта поддерживается (`pydantic-settings`).

## 5. Запуск сервера вручную (smoke)

```bash
$env:FLOWABLE_PASSWORD = "test"     # PowerShell
uv run flowable-mcp
```

Сервер слушает stdio и пишет логи в **stderr**. Если в stderr виден баннер FastMCP или есть `print` в stdout — это баг (СТ-3 нарушен), JSON-RPC сломается.

Завершение — `Ctrl+C`.

## 6. Подключение к Claude Code

Создать или дополнить `.mcp.json` в корне рабочего проекта (где запускается `claude`):

```json
{
  "mcpServers": {
    "flowable": {
      "command": "uv",
      "args": ["--directory", "C:/projects/goober/flowable-mcp", "run", "flowable-mcp"],
      "env": {
        "FLOWABLE_PASSWORD": "test"
      }
    }
  }
}
```

Без `uv` (через установленный entry point):

```json
{
  "mcpServers": {
    "flowable": {
      "command": "C:/projects/goober/flowable-mcp/.venv/Scripts/flowable-mcp.exe",
      "env": { "FLOWABLE_PASSWORD": "test" }
    }
  }
}
```

Проверка внутри Claude Code: `/mcp` — должен появиться сервер `flowable` со списком tool'ов.

## 7. Подключение к Claude Desktop

Файл конфига:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Содержимое аналогично `.mcp.json`:

```json
{
  "mcpServers": {
    "flowable": {
      "command": "uv",
      "args": ["--directory", "C:/projects/goober/flowable-mcp", "run", "flowable-mcp"],
      "env": { "FLOWABLE_PASSWORD": "test" }
    }
  }
}
```

После сохранения — полностью перезапустить Claude Desktop (выйти из трея).

## 8. Типовые сценарии

### Развернуть BPMN и стартовать процесс

```
deploy_bpmn(name="demo", bpmn_xml="<...>")
list_process_definitions(max_results=10)
start_process_instance(process_definition_key="demo-process", variables={"amount": 100})
```

### Найти зависшие задачи

```
list_tasks(assignee="kermit", max_results=50)
list_process_instances(suspended=False, max_results=50)
```

### Посмотреть историю

```
list_historic_process_instances(finished=True, max_results=20)
list_historic_task_instances(process_instance_id="...")
```

### Debug стуавших jobs

```
list_deadletter_jobs(max_results=50)
retry_deadletter_job(job_id="...")
list_event_subscriptions(process_instance_id="...")
```

### Suspend / activate (с предохранителем)

```
suspend_process_definition(process_definition_id="...", confirm_cascade=True)
activate_process_definition(process_definition_id="...", confirm_cascade=True)
```

`confirm_cascade=False` (дефолт) → tool вернёт warning без выполнения, чтобы не остановить рабочие инстансы случайно.

## 9. Troubleshooting

| Симптом | Причина / фикс |
|---------|----------------|
| Клиент не видит tools, в логах `Server failed to start` | Не задан `FLOWABLE_PASSWORD`; pydantic-settings падает с `ValidationError`. |
| `ConnectError` / `ConnectTimeout` при первом вызове | Flowable ещё не прогрелся (`start_period: 60s`). Подождать или проверить `docker compose ps`. |
| `401 Unauthorized` | Несовпадение `FLOWABLE_USERNAME` / `FLOWABLE_PASSWORD` с Flowable. По умолчанию — `rest-admin / test`. |
| `404 Not Found` на корне | `FLOWABLE_BASE_URL` без `/flowable-rest/service`. См. дефолт в §4. |
| JSON-RPC у клиента ломается на первом сообщении | Что-то пишет в stdout (`print`, баннер). Запустить `flowable-mcp` руками, перенаправить stderr в файл, проверить, что в stdout — только JSON. |
| Тесты `tests/integration/` падают с `ConnectionRefused` | Не поднят `docker compose`. См. §2. |
| После `down -v` процессы пропали | Удалён том `flowable-pg`, БД пересоздана с нуля. Это ожидаемо. |

## 10. Известные ограничения (pre-alpha)

- Один процесс-движок (`base_url` один на сервер).
- Нет update-операций для tasks (PUT full-replace в Flowable 8.0 — потенциальный data-loss, до решения не реализуется; см. story S-07).
- Нет историй активностей с фильтром (story S-04 в Revise).
- Нет агрегаций / аналитики на стороне сервера — все фильтры передаются как Flowable query params.

## 11. Полезные ссылки

- Flowable REST API: <https://documentation.flowable.com/latest/develop/rest/>
- Architecture & rules: [`CLAUDE.md`](CLAUDE.md), [`.claude/agents/shared-standards.md`](.claude/agents/shared-standards.md), [`.specify/constitution.md`](.specify/constitution.md)
- Compose: [`docker/flowable/compose.yml`](docker/flowable/compose.yml)
