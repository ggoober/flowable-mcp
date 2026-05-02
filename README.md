# flowable-mcp

MCP server для Flowable BPM Engine 8.x.

Тонкая обёртка над Flowable REST API, превращающая операции движка в MCP-tools для использования в Claude Code / Claude Desktop / других MCP-клиентах.

## Статус

Pre-alpha. Каркас в разработке.

## Стек

- Python 3.12+
- FastMCP
- httpx (async)
- pydantic v2

## Целевой Flowable

`flowable/flowable-rest:8.0.0` (Docker)

## План разработки

В рамках проекта:

- разработка `flowable-mcp` (MCP-сервер поверх Flowable REST API);
- запуск Flowable REST через Docker (`flowable/flowable-rest:8.0.0`) для локальной разработки и тестов;
- покрытие тестами:
  - **unit** — изоляция логики MCP-tools и адаптеров без сети;
  - **integration** — взаимодействие с реальным Flowable REST в Docker;
  - **e2e** — сквозные сценарии через MCP-клиента к Flowable Engine.

## Лицензия

MIT (TBD)
