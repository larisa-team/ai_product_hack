# ai_product_hack

Интеллектуальный аналитический центр на базе ИИ — прототип для хакатона.

Пользователь заводит **проект мониторинга** (тема + текстовые фильтры + источники: RSS-ленты
СМИ и регуляторов, Telegram-каналы), жмёт «Запустить обновление» и получает ленту новостей:
система собирает материалы, отсеивает нерелевантные, схлопывает сообщения об одном событии в
одну карточку, пишет саммари и проставляет категорию, важность и сущности (кто/что/когда/
последствия). Карточку можно отредактировать, скрыть или добавить руками; по ленте работают
фильтры и поиск.

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

### Перед защитой

```bash
make test     # 100 юнит-тестов на чистой логике (контракт, мапперы, mock LLM, парсеры RSS и
              #   t.me/s/, перевод enum'ов, отбор источников, cascade) — ~1с
make smoke    # сквозная проверка: CreateProject -> StartRun -> polling -> итог
curl localhost/api/health   # {"worker": true} — если false, воркер не отвечает по heartbeat
```

Демо-набор источников (5+ источников, 3 категории), проверен из контейнера:
ТАСС и РБК (RSS СМИ), Правительство РФ и ФНС (RSS регуляторов), `cit_gov` и `arppsoft` (Telegram).
Подробнее и про недоступный из контейнера `cbr.ru` — [docs/SYSTEM_DESIGN.md §5](docs/SYSTEM_DESIGN.md).

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
                                    worker ─▶ Postgres + Redis + (t.me/s/ | RSS) + LLM
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
  └─ backend: Run(RUN_STATE_STARTED) + по задаче на канал в Postgres (tasks, kind=extract)

worker (поллинг tasks раз в 2 c)
  ├─ extract:  t.me/s/<channel> → новые посты
  │            (курсор source_cursors.last_msg_id + дедуп по content_hash)
  └─ compose:  когда все extract прогона в статусе done
       ├─ message-filter: LLM батчами по 30 → relevant true/false
       ├─ news-maker:     LLM батчами по 12 → группировка дублей + саммари
       └─ Run(RUN_STATE_DONE) + строки news + stats

фронт: polling GetRun каждые 2 c, пока state == RUN_STATE_STARTED
```

Очередь — таблица `tasks` в Postgres, а не Redis: воркер её поллит, а не блокируется на
чтении. Redis остался только под `claim()` — `SET NX EX`, решает, кто из воркеров реально
исполняет задачу, если несколько одновременно выбрали одну и ту же pending-строку (обычный
`SELECT`, без блокировки), — и под heartbeat для `/api/health`. Воркеров можно
масштабировать: `docker compose up -d --scale worker=2`.

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
    worker/               loop (поллинг tasks), jobs (extract, compose)
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
- [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) — **актуальный инженерный дизайн**: модель данных,
  конвейер, контракт и кодогенерация, критерии приёмки против чек-листа.
- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — вводные и журнал решений команды.
- [docs/SYSTEM_DESIGN_LIGHT.md](docs/SYSTEM_DESIGN_LIGHT.md) — исторический срез: первая
  Telegram-only версия, с которой начинали.
- [PROJECT_SCENARIOS_AND_FILTERS.md](PROJECT_SCENARIOS_AND_FILTERS.md) — сценарии продукта и логика фильтрации.
