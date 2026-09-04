# ai_product_hack

Интеллектуальный аналитический центр на базе ИИ — прототип для хакатона.

Автоматический сбор, дедупликация и саммаризация отраслевых новостей в едином интерфейсе,
с ручным управлением проектами мониторинга и источниками.

Сейчас в репозитории работает **light-версия**: пользователь заводит проект мониторинга
(тема + текстовые фильтры + Telegram-каналы), жмёт «Запустить обновление», и получает
ленту новостей, собранную и саммаризированную LLM.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build          # первая сборка фронта ~5-8 мин (npm install)
```

Открыть **http://localhost**.

Сервисы: `nginx` (:80) → React-статика + прокси `/api`, `backend` (FastAPI, :8000),
`worker` (обработка), `postgres`, `redis`.

Проверка, что всё поднялось:

```bash
curl localhost/api/health
# {"status":"ok","db":true,"redis":true,"llm_provider":"mock"}
```

### LLM

По умолчанию `LLM_PROVIDER=mock` — конвейер работает **без сети и без ключей**, но
фильтрация и саммаризация грубые (эвристики). Для реального качества — RouterAI:

```bash
# .env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://routerai.ru/api/v1
LLM_API_KEY=<ключ RouterAI>
LLM_MODEL=openai/gpt-4o-mini
```

Доступные модели: `curl https://routerai.ru/api/v1/models` (~490 штук). Проверено на
`deepseek/deepseek-v4-flash-0731`: 42 поста с 6 каналов → 25 релевантных → 23 новости,
дубли из разных каналов схлопываются. Прогон ~3 мин.

```bash
docker compose restart worker      # воркер не перечитывает код и env на лету
```

## Как это работает

```
POST /api/projects/{id}/runs
  └─ backend: создаёт Run(STARTED), кладёт по задаче на источник в Redis (q:extract)

worker (BRPOP)
  ├─ extract:  t.me/s/<channel> → новые посты (курсор last_msg_id + дедуп по content_hash)
  └─ compose:  когда все extract готовы
       ├─ message-filter: LLM батчами по 30 → relevant true/false
       └─ news-maker:     LLM один вызов → группировка дублей + саммари
       └─ Run(DONE) + строки news

frontend: polling GET /api/runs/{id} каждые 2 c, пока state != DONE
```

Redis держит очереди (`q:extract`, `q:compose`), claim-ключи «взято в работу»
(`claim:{job_id}`) и счётчик прогресса (`run:{id}:pending`), поэтому воркеров можно
масштабировать: `docker compose up -d --scale worker=2`.

## API

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/projects` | создать проект (name, topic, filters[], sources[]) |
| `GET` | `/api/projects` | список проектов |
| `GET/PATCH/DELETE` | `/api/projects/{id}` | чтение / правка / удаление |
| `POST` | `/api/projects/{id}/runs` | запустить обновление |
| `GET` | `/api/runs/{id}` | статус Run + новости |
| `GET` | `/api/projects/{id}/runs` | история запусков |
| `GET` | `/api/health` | статус сервисов |

Swagger: http://localhost:8000/docs

## Источники

Только Telegram, через публичное веб-превью `t.me/s/<channel>` — без ключей и авторизации.
Канал указывается как `cit_gov`, `@rfrit` или `https://t.me/arppsoft` (нормализуется).

⚠️ Часть каналов отключает веб-превью (напр. `rian_ru`) — оттуда прочитать нельзя,
`extract` вернёт 0 сообщений и залогирует предупреждение.

Проверенные рабочие каналы: `cit_gov`, `rfrit`, `grantsforbussines`, `cio_channel`,
`rustorgpred`, `government_rus`, `arperf`, `icipr`, `arppsoft`, `vedomosti`, `kommersant`,
`telesputnik`.

## Разработка

```bash
docker compose up -d postgres redis backend worker   # без фронта, быстрее
```

- `backend` запущен с `--reload` — правки Python подхватываются автоматически.
- `worker` **не** перезагружается сам: `docker compose restart worker`.
- Схема БД создаётся на старте (`Base.metadata.create_all`), Alembic не используется.
- Отладка экстрактора: `docker compose exec backend python -m app.ingestion.telegram_web cit_gov 7`

```
apps/api/app/
  main.py config.py db.py models.py schemas.py queue.py
  routers/     health.py projects.py runs.py
  ingestion/   telegram_web.py
  llm/         provider.py openai_compat.py mock.py
  worker/      loop.py jobs.py
apps/web/src/  api/client.ts  pages/{ProjectsPage,ProjectPage,RunsPage}.tsx
```

## Документация

- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — консолидированные вводные и журнал решений команды.
- [docs/SYSTEM_DESIGN_LIGHT.md](docs/SYSTEM_DESIGN_LIGHT.md) — **дизайн текущей light-версии** и путь наращивания.
- [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) — полный целевой инженерный проект.
- [proto/monitoring/v1/monitoring.proto](proto/monitoring/v1/monitoring.proto) — контракт данных и API (источник правды, из него генерятся `backend/gen` и `frontend/src/gen`).
- [PROJECT_SCENARIOS_AND_FILTERS.md](PROJECT_SCENARIOS_AND_FILTERS.md) — сценарии продукта и логика фильтрации.
