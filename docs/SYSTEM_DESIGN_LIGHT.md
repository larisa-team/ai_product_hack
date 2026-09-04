# System Design Light

> Упрощённая первая версия. Полный дизайн: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md),
> вводные: [`REQUIREMENTS.md`](./REQUIREMENTS.md). Контракт данных: [`../proto/monitoring/v1/monitoring.proto`](../proto/monitoring/v1/monitoring.proto).
> Запуск — §12, план реализации и статус — §13.

Команда стартует с этой версии и наращивает её до полного дизайна. Задача light-версии — как можно
быстрее получить сквозной путь: **создать проект → запустить Run → получить список новостей**.

---

## 1. Обзор и отличия от полного дизайна

| Аспект | Полный дизайн | **Light** |
|---|---|---|
| Типы источников | RSS, сайты регуляторов, Telegram, архив, ручной ввод | **только Telegram** (`t.me/s/<channel>`) |
| Запуск обработки | ручной + расписание (APScheduler) | **только ручной Run** (`StartRun`/`GetRun`/`ListRuns`) |
| Единица ленты | `NewsItem` — событие, агрегат первоисточников | `News` = `{title, content, sources[]}` внутри Run |
| Дедупликация событий | эмбеддинги + пороги косинуса, окно N дней | **LLM группирует** сам (news-maker, батчами) |
| Саммаризация | 1 вызов на событие, строгий structured output (6 полей) | news-maker батчами по `NEWSMAKER_BATCH` сообщений |
| Категория / важность / тип / сущности | да, от LLM | **нет** в light |
| Ранжирование | движок правил `field`/`semantic` + `protective` | **нет**; порядок = хронология / порядок от LLM |
| Фильтрация | жёсткий отбор + мягкие правила + вью-фильтры | текстовые `filters[].prompt` → LLM relevant/нет |
| Хранилище | SQLite + FTS5 | **Postgres 16** |
| Фон | APScheduler в процессе FastAPI | **отдельный worker + Redis** (очередь, claim, счётчики) |
| Инкрементальность | `last_fetched_at` + `profile_version` + кэш саммари | `source_cursors.last_msg_id` + `content_hash` |
| Поиск | FTS5 `bm25()` | нет (список новостей за Run) |
| API | самописный REST | **Connect-RPC из proto** (`proto/monitoring/v1/monitoring.proto`) |

### Путь наращивания к полному дизайну

1. добавить типы источников (`rss`, `html_site`) рядом с `telegram_web` — тот же интерфейс экстрактора;
2. вынести эмбеддинги + кластеризацию в news-maker (перестать полагаться на LLM-группировку);
3. ввести `NewsItem` с `category/importance/doc_type/entities` (расширить structured output);
4. добавить движок правил ранжирования поверх готовых новостей;
5. добавить расписание в worker (периодический авто-Run проекта).

---

## 2. Топология развёртывания

```mermaid
flowchart LR
    U[Браузер] --> NGINX[nginx]
    NGINX -->|/| REACT[React static]
    NGINX -->|/api| BE[backend<br/>FastAPI]
    BE --> PG[(Postgres)]
    BE -->|enqueue extract| RD[(Redis<br/>очереди + claim + счётчики)]
    W[worker<br/>BRPOP-цикл] --> RD
    W --> PG
    W -->|t.me/s/&lt;channel&gt;| TG[Telegram web preview]
    W -->|filter + news-maker| LLM{{LLM provider<br/>openai_compat / mock}}
```

**Контейнеры** (`docker-compose.yml`): `frontend` (nginx), `backend`, `worker`, `postgres`, `redis`.
`backend` и `worker` — один Docker-образ (`./backend`), разные команды запуска:
`uvicorn app.main:app` и `python -m app.worker.loop`. React собирается multi-stage сборкой, статика
кладётся в образ nginx; nginx отдаёт `/` из статики и проксирует `/api/` → `backend:8000`
(через `resolver 127.0.0.11` + переменную в `proxy_pass`, иначе после рестарта backend'а будет 502).

**Транспорт — Connect поверх HTTP/JSON, без gRPC-сервера и grpc-web прокси.** Реализация —
`backend/app/connect.py`: маршрут `POST /api/{package}.{Service}/{Method}`, реестр методов,
разбор тела сгенерированным `_pb2`-классом, коды Connect → HTTP-статусы.

---

## 3. Модель данных (Postgres)

```mermaid
erDiagram
    PROJECTS ||--o{ RUNS : ""
    PROJECTS ||--o{ MESSAGES : ""
    PROJECTS ||--o{ SOURCE_CURSORS : ""
    RUNS     ||--o{ MESSAGES : ""
    RUNS     ||--o{ NEWS : ""
```

Схема ведётся Alembic (`backend/migrations`), модели — `backend/app/database/models.py`.

```sql
CREATE TABLE projects (
  id VARCHAR PRIMARY KEY,                -- uuid4 строкой (как в proto)
  name VARCHAR(255) NOT NULL,
  topic VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  filters JSONB NOT NULL DEFAULT '[]',   -- список monitoring.v1.ProjectFilter в proto3-JSON
  sources JSONB NOT NULL DEFAULT '[]'    -- список monitoring.v1.Source в proto3-JSON
);

CREATE TABLE runs (
  id VARCHAR PRIMARY KEY,
  project_id VARCHAR NOT NULL REFERENCES projects(id),
  state VARCHAR(50) NOT NULL DEFAULT 'RUN_STATE_STARTED',  -- имя значения enum RunState
  created_at TIMESTAMP NOT NULL,
  stats JSONB NOT NULL DEFAULT '{}'      -- форма monitoring.v1.RunStats
);

CREATE TABLE news (
  id SERIAL PRIMARY KEY,
  run_id VARCHAR NOT NULL REFERENCES runs(id),
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  sources JSONB NOT NULL DEFAULT '[]'    -- ["https://t.me/ch/123", ...]
);

-- Ниже — служебные таблицы, наружу в proto не выходят.

CREATE TABLE messages (
  id SERIAL PRIMARY KEY,
  project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_id     VARCHAR NOT NULL REFERENCES runs(id)     ON DELETE CASCADE,
  channel VARCHAR(255) NOT NULL,
  tg_msg_id BIGINT NOT NULL,
  url TEXT NOT NULL,
  text TEXT NOT NULL,
  posted_at TIMESTAMP,
  content_hash VARCHAR(64) NOT NULL,
  relevant BOOLEAN,                      -- NULL до message-filter
  CONSTRAINT uq_messages_hash UNIQUE (project_id, content_hash)   -- кросс-Run дедуп
);

CREATE TABLE source_cursors (
  project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  channel VARCHAR(255) NOT NULL,
  last_msg_id BIGINT,                    -- курсор инкрементального чтения
  PRIMARY KEY (project_id, channel)
);
```

**Почему `filters`/`sources` — JSONB, а курсор — отдельная таблица.** JSONB хранит вложенные
структуры ровно в форме proto3-JSON соответствующих сообщений, поэтому конвертация в
`services/mappers.py` — это `ParseDict`/`MessageToDict`, без ручного перекладывания полей.
Служебный `last_msg_id` подмешивать в этот JSONB нельзя — схема разъедется с proto,
поэтому он живёт в `source_cursors`.

---

## 4. Жизненный цикл Run

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant BE as backend
    participant RD as Redis
    participant W as worker
    participant TG as t.me/s/
    participant LLM as LLM

    FE->>BE: POST /api/monitoring.v1.RunService/StartRun
    BE->>BE: INSERT runs(state=RUN_STATE_STARTED)
    BE->>RD: SET run:{run}:pending = N каналов
    loop по каждому каналу из project.sources
        BE->>RD: RPUSH q:extract {run, project, channel}
    end
    BE-->>FE: StartRunResponse{run}

    loop worker BLPOP q:extract / q:compose
        W->>RD: SET claim:{job_id} NX EX 600
        alt claim получен
            W->>TG: GET t.me/s/<channel>?before=... (до last_msg_id / лимита / глубины)
            TG-->>W: посты
            W->>W: INSERT messages ON CONFLICT DO NOTHING (project_id, content_hash)
            W->>W: UPSERT source_cursors.last_msg_id
            W->>RD: DECR run:{run}:pending
            opt счётчик == 0
                W->>RD: RPUSH q:compose {run}
            end
        end
    end

    W->>W: compose: SELECT * FROM messages WHERE run_id={run}
    alt сообщений нет
        W->>W: runs.state=RUN_STATE_DONE, stats={collected:0,...}
    else
        W->>LLM: message-filter, батчи по FILTER_BATCH -> relevant true/false
        W->>W: messages.relevant = ...
        W->>LLM: news-maker, батчи по NEWSMAKER_BATCH -> [{title, content, message_indices}]
        W->>W: INSERT news(sources = uniq url группы)
        W->>W: runs.state=RUN_STATE_DONE, stats={collected, relevant, news}
    end

    FE->>BE: GetRun (polling каждые 2 c)
    BE-->>FE: GetRunResponse{run: {state, stats, news[]}}
```

Ошибка на этапе compose (недоступный LLM, невалидный JSON после ретраев) → `RUN_STATE_FAILED`
и `stats.error`; воркер продолжает работу.

### Redis-ключи

| Ключ | Тип | Назначение |
|---|---|---|
| `q:extract`, `q:compose` | list | очереди задач (`RPUSH` / `BLPOP`) |
| `claim:{job_id}` | string, `SET NX EX 600` | «взято в работу» — параллельные worker'ы и повторные enqueue не дублируют обработку |
| `run:{run_id}:pending` | integer, `DECR` | сколько extract-задач осталось; последний инициирует `compose` |

`job_id`: `"{run_id}:{channel}"` для extract, `"compose:{run_id}"` для compose.

### Отказоустойчивость (light-уровень)

- worker умер посреди задачи → `claim:{job_id}` истекает через TTL, задачу можно перезапустить;
- «завис» Run (в `RUN_STATE_STARTED` дольше N минут) → повторный `StartRun` создаёт новый Run;
- ошибка LLM/парсинга в compose → `RUN_STATE_FAILED`, `stats.error`, новости не создаются.

---

## 5. Обработка (LLM)

Провайдер за абстракцией `app/llm/provider.py` — два метода: `filter_relevance(topic, extra, texts)`
и `make_news(topic, messages)`. `LLM_PROVIDER = openai_compat | mock`.
`openai_compat` рассчитан на OpenAI-совместимые API. Используем **RouterAI**:
`LLM_BASE_URL=https://routerai.ru/api/v1` (клиент сам добавляет `/chat/completions`),
`LLM_MODEL=openai/gpt-4o-mini`. Запрос — `response_format: {"type":"json_object"}` + починка JSON
с ретраем ×3. Оффлайн-демо — на `mock`.

### message-filter (батч ~30 сообщений)

```
system: Ты фильтр релевантности для мониторинга темы «{topic}».
        Дополнительные указания пользователя: {filters[].prompt, через "; "}.
        Для каждого сообщения верни relevant: true|false. Только JSON.
user:   [{"i":0,"text":"..."}, {"i":1,"text":"..."}, ...]
schema: {"results":[{"i":int,"relevant":bool}]}
```

`mock`: `relevant = любая лемма из topic присутствует в тексте` (pymorphy3).

### news-maker (батчами по `NEWSMAKER_BATCH`, relevant с обрезкой до `NEWSMAKER_CAP` свежих)

```
system: Сгруппируй сообщения об одном и том же событии и сделай из каждой группы новость.
        Тема мониторинга: «{topic}». Заголовок — короткий, content — 3–5 предложений по сути.
        Только JSON.
user:   [{"i":0,"channel":"...","text":"..."}, ...]
schema: {"news":[{"title":str,"content":str,"message_indices":[int]}]}
```

Ответ обёрнут в объект (`{"news":[...]}`), т.к. `response_format: json_object` не допускает голый
массив. `url` в запрос не передаём — восстанавливаем по индексу `i` при записи.

**Почему батчами.** На вход из ~30 сообщений reasoning-модель (`deepseek-v4-flash`) тратила
21k reasoning-токенов и возвращала результат лишь по 1–2 сообщениям. Режем вход на
`NEWSMAKER_BATCH` (12) сообщений, индексы внутри батча сдвигаем обратно в общий список.
Порядок хронологический, поэтому посты об одном событии обычно попадают в один батч.
Замер на 6 каналах: было `relevant 28 → news 1`, стало `relevant 29 → news 27`.
`News.sources` = уникальные `url` сообщений группы.
`mock`: группировка по совпадению первых 4 слов сообщения; `content` = самое длинное сообщение
группы (обрезка до 800 символов).

---

## 6. API — Connect-RPC из proto

Транспорт: **Connect поверх HTTP/JSON**. Адрес метода складывается из полного имени сервиса
в proto и имени RPC:

```
POST /api/{package}.{Service}/{Method}
Content-Type: application/json
тело      — сообщение Request  в proto3-JSON
200       — сообщение Response в proto3-JSON
ошибка    — HTTP-код + {"code": "...", "message": "..."}
```

| RPC | Путь |
|---|---|
| `ProjectService.CreateProject` | `POST /api/monitoring.v1.ProjectService/CreateProject` |
| `ProjectService.GetProject` | `POST /api/monitoring.v1.ProjectService/GetProject` |
| `ProjectService.ListProjects` | `POST /api/monitoring.v1.ProjectService/ListProjects` |
| `ProjectService.UpdateProject` | `POST /api/monitoring.v1.ProjectService/UpdateProject` |
| `ProjectService.DeleteProject` | `POST /api/monitoring.v1.ProjectService/DeleteProject` |
| `RunService.StartRun` | `POST /api/monitoring.v1.RunService/StartRun` |
| `RunService.GetRun` | `POST /api/monitoring.v1.RunService/GetRun` |
| `RunService.ListRuns` | `POST /api/monitoring.v1.RunService/ListRuns` |

Плюс служебный `GET /api/health` — вне контракта, инфраструктурный (отдаёт также реестр
зарегистрированных RPC).

Коды ошибок Connect → HTTP: `invalid_argument` 400, `not_found` 404, `failed_precondition` 412,
`unimplemented` 501, `internal` 500.

```jsonc
// CreateProject
{ "name": "ИТ-мониторинг", "topic": "цифровые технологии, гранты",
  "filters": [{"prompt": "не интересны поздравления"}],
  "sources": [{"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov"}] }

// GetRun
{ "run": { "id": "...", "projectId": "...", "state": "RUN_STATE_DONE",
           "createdAt": "2026-09-04T13:28:00Z",
           "stats": {"collected": 40, "relevant": 29, "news": 27},
           "news": [{"title": "...", "content": "...", "sources": ["https://t.me/ch/1"]}] } }
```

### Где контракт реально проверяется

| Сторона | Механизм | Что происходит при расхождении |
|---|---|---|
| Backend | `json_format.Parse(body, RequestPb(), ignore_unknown_fields=False)` | `400 invalid_argument` с перечислением допустимых полей |
| Backend | `services/mappers.py` — единственное место ORM ↔ protobuf | смена proto ломает сборку сообщения в одном месте |
| Backend | `connect.py` сверяет тип ответа хендлера с объявленным в proto | `500 internal` |
| Frontend | `createPromiseClient(ProjectService, transport)` из `src/gen/` | ошибка `tsc` (`TS2353: ... does not exist in type PartialMessage<...>`) |
| Оба | `make lint` (buf) + `make generate` в чеклисте перед коммитом | несогласованный proto не пройдёт review |

Терсность proto3-JSON: поля со значением по умолчанию в ответе опускаются, поэтому
`stats` со всеми нулями приходит как `{}` — сгенерированный клиент подставляет нули сам.

---

## 7. Frontend (3 экрана)

| Путь | Экран | Содержимое |
|---|---|---|
| `/` | **Projects** | список проектов + форма создания: `name`, `topic`, повторяемые поля «текстовый фильтр» и «Telegram-канал» |
| `/projects/:id` | **Project** | данные проекта; кнопка «Запустить обновление» → `StartRun` → polling `GetRun` каждые 2 c; плашка `stats`; лента карточек `News` (`title`, `content`, ссылки-источники) |
| `/projects/:id/runs` | **Runs** | история запусков со `state` и `stats` |

Стек: React + Vite + TS, TanStack Query (polling), Mantine.
Клиент — сгенерированный: `src/api/client.ts` создаёт
`createConnectTransport({ baseUrl: "/api" })` и `createPromiseClient(ProjectService | RunService)`.
Типы `Project`, `Run`, `News`, `RunState`, `SourceType` берутся из `src/gen/`, руками не пишутся:
enum `RunState.DONE` вместо строки, `run.createdAt.toDate()`, `run.stats?.collected`.

---

## 8. Конфигурация (ENV)

`backend/app/config.py`, значения по умолчанию — в `.env.example`. Секреты кладутся в `.env`
(в git не попадает).

| Переменная | Default | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://app:app@postgres:5432/app` | Postgres. Alembic сам подменяет драйвер на синхронный |
| `REDIS_URL` | `redis://redis:6379/0` | Redis |
| `CORS_ORIGINS` | `http://localhost` | адрес фронта |
| `DEBUG` | `false` | уровень логов, echo SQL |
| `LLM_PROVIDER` | `mock` | `openai_compat` \| `mock` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | — | для `openai_compat` (RouterAI) |
| `TG_FETCH_LIMIT` | `100` | максимум постов на канал за прогон |
| `TG_FETCH_DAYS` | `7` | глубина чтения канала |
| `FILTER_BATCH` | `30` | размер батча message-filter |
| `NEWSMAKER_CAP` | `100` | максимум relevant-сообщений, уходящих в news-maker |
| `NEWSMAKER_BATCH` | `12` | сообщений на один вызов news-maker |

---

## 9. docker-compose

```
postgres:  postgres:16-alpine, том pgdata, healthcheck pg_isready
redis:     redis:7-alpine, healthcheck redis-cli ping
backend:   build ./backend, uvicorn app.main:app --reload, :8000, код примонтирован
worker:    build ./backend (тот же образ), python -m app.worker.loop
frontend:  build ./frontend (multi-stage: node build -> nginx со статикой), :80
```

`backend` и `worker` делят один образ и общий блок переменных (YAML-anchor `x-backend-env`).
`PYTHONPATH=/app:/app/gen`, чтобы работал `from monitoring.v1 import monitoring_pb2`.

Воркеров можно масштабировать: `docker compose up -d --scale worker=2` — задачи разбираются
через `BLPOP`, повторный захват отсекается `claim`-ключом.

---

## 10. Контракт и кодогенерация

Источник правды — [`proto/monitoring/v1/monitoring.proto`](../proto/monitoring/v1/monitoring.proto).
Дублирующий `x.proto` в корне удалён.

```bash
make lint       # buf lint
make generate   # backend/gen/*.py  +  frontend/src/gen/*.ts
make proto-all  # то и другое
```

Сгенерированное **коммитится** (`backend/gen/`, `frontend/src/gen/`): `docker compose build`
копирует `gen/` из контекста сборки, иначе образ не соберётся без предварительной генерации.
Правило: изменил `.proto` → `make generate` → коммить вместе.

### Что было дописано в контракт под функциональность

```proto
enum RunState {
  ...
  RUN_STATE_FAILED = 3;      // прогон упал (LLM недоступен и т.п.)
}

// Итоги прогона: сколько собрано, сколько прошло фильтр, сколько новостей получилось.
message RunStats {
  int32 collected = 1;
  int32 relevant = 2;
  int32 news = 3;
  string error = 4;          // заполняется только при RUN_STATE_FAILED
}

message Run {
  ...
  RunStats stats = 6;
}
```

### Замечание по `FilterType`

У `FilterType` нулевое значение содержательное (`PROMT_BASED = 0`), поэтому в proto3-JSON оно
всегда опускается и «не задан» от «prompt-based» неотличимо. Пока тип фильтра один — это
безвредно. При появлении второго стоит добавить `FILTER_TYPE_UNSPECIFIED = 0` и сдвинуть
остальные (ломающее изменение, поймается `buf breaking`).

---

## 11. Критерии приёмки

Все пройдены на живом стеке.

- [x] `make proto-all` — `buf lint` чист, генерация Python + TS без ошибок.
- [x] `make up` поднимает `frontend, backend, worker, postgres, redis`;
      `GET /api/health` = 200 и показывает `db`, `redis`, `llm_provider` и реестр RPC.
- [x] `make migrate` — таблицы `projects, runs, news, messages, source_cursors`.
- [x] Полный CRUD через Connect: Create → Get → List → Update (`update_mask` уважается) → Delete.
- [x] **Контроль контракта, бэкенд:** лишнее поле в запросе → `400 invalid_argument`
      с перечислением допустимых полей.
- [x] **Контроль контракта, фронт:** поле не из proto → ошибка `tsc` `TS2353`.
- [x] `StartRun` на 6 каналах заказчика → polling `GetRun` → `RUN_STATE_DONE`,
      `stats={collected:40, relevant:29, news:27}`, дубли из разных каналов схлопнуты.
- [x] Повторный `StartRun` → `collected:0`, новых строк в `messages` нет (курсор + `content_hash`).
- [x] `LLM_PROVIDER=mock` — весь путь работает без сети.
- [x] `--scale worker=2` — одна задача не берётся дважды.
- [x] Недоступный LLM → `RUN_STATE_FAILED` + `stats.error`, воркер жив.
- [x] Фронт: `npm run build` без ошибок типов; в браузере — создание проекта, запуск, лента, история.

---

## 12. Как запускать

### Поднять

```bash
cd ~/ai_product_hack
make up          # создаст .env из .env.example, соберёт и поднимет стек
make migrate     # применить миграции
```

Открыть **http://localhost**. Первая сборка фронта — 5–8 минут (`npm install`), дальше секунды.

```bash
curl localhost/api/health
# {"status":"ok","db":true,"redis":true,"llm_provider":"mock","rpc":{...}}
```

### Завершить

```bash
make down        # остановить, данные Postgres сохраняются в томе
make db-reset    # + снести том (проекты и новости пропадут)
```

### Повседневное

```bash
make ps                                 # что запущено
make logs                               # логи воркера (make logs s=backend)
make dev                                # стек без фронта — быстрее для бэкенда
docker compose up -d worker             # после правок worker/ llm/ ingestion
docker compose up -d --scale worker=2   # два воркера
make proto-all                          # после правки .proto
```

- `backend` запущен с `--reload` — правки Python подхватываются автоматически;
- `worker` **не** перезагружается сам;
- отладка экстрактора:
  `docker compose exec backend python -m app.ingestion.telegram_web cit_gov 7`.

### Подключение реального LLM (RouterAI)

По умолчанию `LLM_PROVIDER=mock` — без сети и ключей, но фильтрация и саммаризация грубые.

```bash
# .env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://routerai.ru/api/v1
LLM_API_KEY=<ключ RouterAI>
LLM_MODEL=deepseek/deepseek-v4-flash-0731
```

```bash
docker compose up -d worker backend
```

Список моделей — `curl https://routerai.ru/api/v1/models` (~490).

### Грабли, на которые уже наступили

- **502 через nginx после рестарта backend** — nginx кеширует IP апстрима. Лечится
  `resolver 127.0.0.11` + переменной в `proxy_pass` (уже в `frontend/nginx.conf`).
- **Воркер стартует со старого образа** — если compose переиспользовал тег от прежней сборки,
  нужен `docker compose up -d --build` (или `docker compose down --remove-orphans`).
- **Тихий откат на `mock`** — если пропал `.env`, `LLM_PROVIDER` берёт значение по умолчанию.
  Проверяется `curl localhost/api/health`.
- **Сборка из WSL падает на `docker-credential-desktop.exe`**:
  ```bash
  mkdir -p /tmp/dockercfg && echo '{"auths":{}}' > /tmp/dockercfg/config.json
  DOCKER_CONFIG=/tmp/dockercfg docker compose up -d --build
  ```

---

## 13. План реализации (как это делалось)

Работа шла в два захода. Сначала собрали работающую light-версию на самописном REST
(`apps/api` + `apps/web`), затем перевели её на proto-first каркас команды.

### Этап 1 — рабочий прототип (10 шагов)

| # | Шаг | Чем проверено |
|---|---|---|
| 1 | Документация + приведение proto к валидному proto3 | ручная сверка |
| 2 | Каркас репозитория, `docker-compose.yml` | сервисы поднялись, health |
| 3 | БД и модели | таблицы созданы |
| 4 | CRUD проектов | create → list → patch → 404 → delete + cascade |
| 5 | Telegram-экстрактор (`t.me/s/`, пагинация, `content_hash`, `NoPreviewError`) | 30 постов с `meduzalive`, курсор фильтрует |
| 6 | Очередь Redis + воркер (extract) | 11 сообщений без дублей, claim отсекает повтор |
| 7 | LLM-провайдер + compose (filter + news-maker) | mock без сети; недоступный LLM → FAILED |
| 8 | Чтение Run | polling STARTED → DONE |
| 9 | Фронтенд (3 экрана) | `tsc` чист, сквозной путь через nginx |
| 10 | Сборка e2e, README | все критерии приёмки |

### Этап 2 — перевод на proto-first (8 шагов)

| # | Шаг | Что появилось | Чем проверено |
|---|---|---|---|
| 1 | Расширение proto | `RunStats`, `Run.stats`, `RUN_STATE_FAILED` | `buf lint` = 0, оба `gen/` содержат новые типы |
| 2 | Connect-адаптер + каркас backend | `app/connect.py`, `main.py`, `queue.py`, Dockerfile | health с реестром RPC; несуществующий RPC → 501 |
| 3 | Модель БД под перенесённую логику | `Message`, `SourceCursor`, `Run.stats`, миграция | дедуп, upsert курсора |
| 4 | Мапперы + `ProjectService` | `services/mappers.py`, `api/project_api.py` | CRUD; `update_mask`; **лишнее поле → 400** |
| 5 | Перенос ingestion / llm на async | `ingestion/`, `llm/` | живой канал; mock; RouterAI |
| 6 | `RunService` + воркер | `run_service.py`, `run_api.py`, `worker/` | 22 → 15 → 15; идемпотентность; 2 воркера; FAILED |
| 7 | Фронт на сгенерированном клиенте | `api/client.ts`, 3 страницы | `tsc` чист; **поле не из proto → TS2353** |
| 8 | Уборка и документация | удалён `apps/`, цели в `Makefile`, README/CONTRIBUTING/этот документ | `make up` с нуля |

### Что чинили по ходу второго этапа

1. **news-maker захлёбывался.** На ~30 сообщениях reasoning-модель тратила 21k токенов
   на размышления и возвращала 1–2 группы. Ввели `NEWSMAKER_BATCH` — стало 27 новостей из 29.
2. **nginx отдавал 502** после рестарта backend — кешировал IP. `resolver` + переменная в `proxy_pass`.
3. **Alembic ходил на захардкоженный `localhost`** — переведён на `settings.DATABASE_URL`.
4. **`runs.stats NOT NULL` без дефолта** — миграция упала бы на непустой таблице,
   добавлен `server_default '{}'::jsonb`.

### Что осталось за рамками

- нет RSS/HTML-коннекторов (Кабельщик и часть сайтов) — см. путь наращивания в §1;
- нет расписания, ранжирования, категорий/важности, поиска — всё это в
  [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md);
- пагинация в `ListProjects`/`ListRuns` реализована по `page_token`, но фронт её пока не использует.
