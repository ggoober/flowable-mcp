# flowable-mcp — Profile

cwd: C:\projects\goober\flowable-mcp

## Overview

- **Type:** MCP server (single-service)
- **Stack:** Python 3.12+, FastMCP, httpx (async), pydantic v2
- **Status:** pre-alpha
- **Phase:** scaffolding
- **Repo:** https://github.com/ggoober/flowable-mcp (private)

## Description

MCP-сервер поверх Flowable BPM Engine 8.x REST API. Тонкая обёртка, превращающая операции движка процессов (BPMN/CMMN/DMN, runtime, history, management) в MCP-tools для использования в Claude Code / Claude Desktop и других MCP-клиентах.

## Target Engine

- `flowable/flowable-rest:8.0.0` (Docker)
- Default URL: `http://localhost:8080/flowable-rest`
- Default auth: Basic `rest-admin:test`
- Compose-файл: `C:\projects\goober\cortex-dev\docker\flowable\docker-compose.yml`

## Architecture

```
┌─────────────────────────────────────────────────┐
│         Claude Code / Claude Desktop             │
│              (MCP client)                        │
└──────────────────┬──────────────────────────────┘
                   │ MCP (stdio / SSE), JSON-RPC 2.0
┌──────────────────▼──────────────────────────────┐
│            flowable-mcp (Python)                 │
│                                                  │
│  FastMCP Server                                  │
│    ↓                                             │
│  Tool Layer (process / task / history /          │
│              debug / admin)                      │
│    ↓                                             │
│  FlowableClient (httpx async)                    │
│    ↓                                             │
│  Config (env / .mcp.json)                        │
└──────────────────┬──────────────────────────────┘
                   │ HTTPS / Basic Auth
┌──────────────────▼──────────────────────────────┐
│      flowable-rest:8.0.0 (Docker, :8080)         │
│      BPMN / CMMN / DMN / IDM engines             │
└──────────────────────────────────────────────────┘
```

## Project Structure (planned)

```
flowable-mcp/
├── pyproject.toml              # fastmcp, httpx, pydantic
├── README.md
├── profile.md
├── .env.example
├── src/flowable_mcp/
│   ├── server.py               # FastMCP() + регистрация tools
│   ├── config.py               # pydantic-settings
│   ├── client.py               # FlowableClient (httpx.AsyncClient)
│   ├── errors.py
│   ├── models.py
│   └── tools/
│       ├── process.py
│       ├── task.py
│       ├── history.py
│       ├── debug.py
│       └── admin.py
└── tests/
```

## Roadmap

### v0.1 — Process + Task tools
- `deploy_bpmn`, `list_process_definitions`, `start_process`, `get_process_instance`, `list_active_instances`, `suspend_process`
- `list_tasks`, `claim_task`, `complete_task`, `get_task`

### v0.2 — Monitoring & Debug
- `get_diagram` (PNG), `get_active_activities`, `get_variables`, `get_history`
- `list_deadletter_jobs`, `retry_job`, engine info, db tables

### v0.3 — CMMN, DMN, Event Registry
- Cases, decisions, event subscriptions

### v0.4 — Observability
- Prometheus-метрики самого MCP, structured logging

## Deployment

1. **Локально (stdio)** — рядом с Claude Code, `.mcp.json`:
   ```json
   {
     "mcpServers": {
       "flowable": {
         "command": "python",
         "args": ["-m", "flowable_mcp"],
         "env": { "FLOWABLE_BASE_URL": "http://localhost:8080/flowable-rest" }
       }
     }
   }
   ```
2. **Docker (SSE)** — рядом с flowable-rest в общей сети.

## Key Contacts

- **Owner:** Denis Tskhay

## Links

- **GitHub:** https://github.com/ggoober/flowable-mcp
- **Junction:** C:\cortex\projects\flowable-mcp → C:\projects\goober\flowable-mcp
- **Flowable docs:** https://documentation.flowable.com/latest/develop/rest/
