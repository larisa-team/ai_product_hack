# ai_product_hack

Интеллектуальный аналитический центр на базе ИИ — прототип для хакатона.

Пользователь заводит **проект мониторинга** (тема + текстовые фильтры + Telegram-каналы),
жмёт «Запустить обновление» и получает ленту новостей: система собирает посты, отсеивает
нерелевантные, схлопывает дубли из разных каналов и пишет саммари.

Контракт API и модели данных описан в **[proto](proto/monitoring/v1/monitoring.proto)** —
это источник правды, из него генерируются типы для бэкенда и фронтенда.

## Быстрый старт

```bash
make up          # поднимет всё; первая сборка фронта ~5-8 мин (npm install)
make migrate     # применить миграции
```

Открыть **http://localhost**.

```bash
curl localhost/api/health
# {"status":"ok","db":true,"redis":true,"llm_provider":"mock","rpc":{...}}
```

Все команды — `make help`.

### LLM

По умолчанию `LLM_PROVIDER=mock` — конвейер работает **без сети и без ключей**, но фильтрация
и саммаризация грубые (эвристики). Для реального качества — RouterAI:

```bash
# .env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://routerai.ru/api/v1
LLM_API_KEY=<ключ RouterAI>
LLM_MODEL=deepseek/deepseek-v4-flash-0731
```

```bash
docker compose up -d worker    # воркер не перечитывает env на лету
```

Каталог моделей: `curl https://routerai.ru/api/v1/models` (~490 штук).

## Архитектура

```
              ┌── React (статика) ──┐
браузер ─▶ nginx ─┤                 │
              └── /api ─▶ backend (FastAPI, Connect-RPC) ─▶ Postgres
                                    worker ─▶ Postgres + Redis + t.me + LLM
```

API — **Connect-протокол поверх HTTP/JSON**, без gRPC-сервера и grpc-web прокси:

```
POST /api/monitoring.v1.ProjectService/CreateProject
POST /api/monitoring.v1.RunService/StartRun
```

Запрос разбирается сгенерированным из proto классом, поэтому поле, которого нет в контракте,
отбивается с `400 invalid_argument`. Фронт ходит сгенерированным Connect-клиентом, так что
то же расхождение ловится ещё на `tsc`.

### Как идёт обработка

```
StartRun
  └─ backend: Run(RUN_STATE_STARTED) + по задаче на канал в Redis (q:extract)

worker (BRPOP)
  ├─ extract:  t.me/s/<channel> → новые посты
  │            (курсор source_cursors.last_msg_id + дедуп по content_hash)
  └─ compose:  когда все extract готовы
       ├─ message-filter: LLM батчами по 30 → relevant true/false
       ├─ news-maker:     LLM батчами по 12 → группировка дублей + саммари
       └─ Run(RUN_STATE_DONE) + строки news + stats

фронт: polling GetRun каждые 2 c, пока state == RUN_STATE_STARTED
```

Redis держит очереди, claim-ключи «взято в работу» и счётчик прогресса, поэтому воркеров
можно масштабировать: `docker compose up -d --scale worker=2`.

## Источники

Только Telegram, через публичное веб-превью `t.me/s/<channel>` — без ключей и авторизации.
Канал указывается как `cit_gov`, `@rfrit` или `https://t.me/arppsoft` (нормализуется).

⚠️ Часть каналов отключает веб-превью (напр. `rian_ru`) — оттуда прочитать нельзя,
`extract` вернёт 0 сообщений и залогирует предупреждение.

Проверенные рабочие каналы: `cit_gov`, `rfrit`, `grantsforbussines`, `cio_channel`,
`rustorgpred`, `government_rus`, `arperf`, `icipr`, `arppsoft`, `vedomosti`, `kommersant`,
`telesputnik`.

## Структура

```
proto/monitoring/v1/monitoring.proto   контракт — источник правды
backend/
  gen/                    сгенерированные Python-классы (make generate)
  app/
    connect.py            сервер Connect-протокола (реестр RPC, валидация по схеме)
    main.py config.py queue.py
    api/                  реализации RPC: project_api, run_api, registry
    services/             mappers (ORM ↔ protobuf), project_service, run_service
    database/             models, session, repositories
    ingestion/            telegram_web
    llm/                  provider, openai_compat (RouterAI), mock
    worker/               loop (BRPOP), jobs (extract, compose)
  migrations/             Alembic
frontend/
  src/gen/                сгенерированные TS-типы и Connect-клиенты (make generate)
  src/api/client.ts       createConnectTransport + промис-клиенты
  src/pages/              ProjectsPage, ProjectPage, RunsPage
```

## Разработка

См. [CONTRIBUTING.md](CONTRIBUTING.md) — установка тулинга, кодогенерация, рабочий процесс.

```bash
make dev                  # стек без фронта, быстрее
make logs                 # логи воркера (make logs s=backend)
make proto-all            # buf lint + перегенерация после правки proto
```

- `backend` запущен с `--reload` — правки Python подхватываются автоматически;
- `worker` **не** перезагружается сам: `docker compose up -d worker`;
- отладка экстрактора: `docker compose exec backend python -m app.ingestion.telegram_web cit_gov 7`.

## Документация

- [CONTRIBUTING.md](CONTRIBUTING.md) — как развернуть и как работать с proto.
- [docs/SYSTEM_DESIGN_LIGHT.md](docs/SYSTEM_DESIGN_LIGHT.md) — **дизайн текущей версии** и путь наращивания.
- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — вводные и журнал решений команды.
- [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) — полный целевой инженерный проект.
- [PROJECT_SCENARIOS_AND_FILTERS.md](PROJECT_SCENARIOS_AND_FILTERS.md) — сценарии продукта и логика фильтрации.
