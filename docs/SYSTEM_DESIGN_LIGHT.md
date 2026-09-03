# System Design Light

> Упрощённая первая версия. Полный дизайн: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md),
> вводные: [`REQUIREMENTS.md`](./REQUIREMENTS.md). Контракт данных: [`../x.proto`](../x.proto).
> План реализации по пунктам ведётся отдельно.

Команда стартует с этой версии и наращивает её до полного дизайна. Задача light-версии — как можно
быстрее получить сквозной путь: **создать проект → запустить Run → получить список новостей**.

---

## 1. Обзор и отличия от полного дизайна

| Аспект | Полный дизайн | **Light** |
|---|---|---|
| Типы источников | RSS, сайты регуляторов, Telegram, архив, ручной ввод | **только Telegram** (`t.me/s/<channel>`) |
| Запуск обработки | ручной + расписание (APScheduler) | **только ручной Run** (`StartRun`/`GetRun`/`ListRuns`) |
| Единица ленты | `NewsItem` — событие, агрегат первоисточников | `News` = `{title, content, sources[]}` внутри Run |
| Дедупликация событий | эмбеддинги + пороги косинуса, окно N дней | **LLM группирует** сам в одном вызове news-maker |
| Саммаризация | 1 вызов на событие, строгий structured output (6 полей) | 1 вызов news-maker на весь Run |
| Категория / важность / тип / сущности | да, от LLM | **нет** в light |
| Ранжирование | движок правил `field`/`semantic` + `protective` | **нет**; порядок = хронология / порядок от LLM |
| Фильтрация | жёсткий отбор + мягкие правила + вью-фильтры | текстовые `filters[].prompt` → LLM relevant/нет |
| Хранилище | SQLite + FTS5 | **Postgres 16** |
| Фон | APScheduler в процессе FastAPI | **отдельный worker + Redis** (очередь, claim, счётчики) |
| Инкрементальность | `last_fetched_at` + `profile_version` + кэш саммари | курсор `source.last_msg_id` + `content_hash` |
| Поиск | FTS5 `bm25()` | нет (список новостей за Run) |

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

**Контейнеры** (`docker-compose.yml`): `nginx`, `backend`, `worker`, `postgres`, `redis`.
`backend` и `worker` — один Docker-образ (`apps/api`), разные команды запуска:
`uvicorn app.main:app` и `python -m app.worker.loop`. React собирается multi-stage сборкой, статика
кладётся в образ `nginx`; `nginx` отдаёт `/` из статики и проксирует `/api/` → `backend:8000`.

---

## 3. Модель данных (Postgres)

```mermaid
erDiagram
    PROJECT ||--o{ PROJECT_FILTER : ""
    PROJECT ||--o{ SOURCE : ""
    PROJECT ||--o{ RUN : ""
    PROJECT ||--o{ MESSAGE : ""
    SOURCE  ||--o{ MESSAGE : ""
    RUN     ||--o{ MESSAGE : ""
    RUN     ||--o{ NEWS : ""
```

Эскиз DDL:

```sql
CREATE TABLE project (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  topic TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project_filter (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  prompt TEXT NOT NULL
);

CREATE TABLE source (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  type TEXT NOT NULL DEFAULT 'telegram',
  telegram TEXT NOT NULL,               -- '@channel' | 't.me/channel' | 'channel'
  last_msg_id BIGINT                     -- курсор инкрементального чтения
);

CREATE TABLE run (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  state TEXT NOT NULL DEFAULT 'STARTED'  -- STARTED | DONE | FAILED
        CHECK (state IN ('STARTED','DONE','FAILED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  stats JSONB NOT NULL DEFAULT '{}'      -- {collected, relevant, news, error?}
);
CREATE INDEX ix_run_project ON run(project_id, created_at DESC);

CREATE TABLE message (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  source_id  UUID NOT NULL REFERENCES source(id)  ON DELETE CASCADE,
  run_id     UUID NOT NULL REFERENCES run(id)     ON DELETE CASCADE,
  tg_channel TEXT NOT NULL,
  tg_msg_id  BIGINT NOT NULL,
  url        TEXT NOT NULL,
  text       TEXT NOT NULL,
  posted_at  TIMESTAMPTZ,
  content_hash TEXT NOT NULL,
  relevant   BOOLEAN,                    -- NULL до фильтра
  UNIQUE (project_id, content_hash)      -- кросс-Run дедуп
);
CREATE INDEX ix_message_run ON message(run_id);

CREATE TABLE news (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id     UUID NOT NULL REFERENCES run(id)     ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  title   TEXT NOT NULL,
  content TEXT NOT NULL,
  sources JSONB NOT NULL DEFAULT '[]',   -- ["https://t.me/ch/123", ...]
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_news_run ON news(run_id);
```

Схема создаётся `Base.metadata.create_all` на старте backend (Alembic в light не заводим).

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

    FE->>BE: POST /api/projects/{id}/runs
    BE->>BE: INSERT run(state=STARTED)
    BE->>RD: SET run:{run}:pending = N источников
    loop по каждому источнику
        BE->>RD: LPUSH q:extract {run, source}   (job_id = "{run}:{source}")
    end
    BE-->>FE: 201 Run{STARTED}

    loop worker BRPOP q:extract / q:compose
        W->>RD: SET claim:{job_id} NX EX 600
        alt claim получен
            W->>TG: GET t.me/s/<channel>?before=... (до last_msg_id / лимита / глубины)
            TG-->>W: посты
            W->>W: content_hash; пропуск дублей (project_id, content_hash)
            W->>BE Deferred: INSERT message(run_id=...)
            W->>W: UPDATE source.last_msg_id
            W->>RD: DECR run:{run}:pending
            opt счётчик == 0
                W->>RD: LPUSH q:compose {run}
            end
        end
    end

    W->>W: compose: msgs = SELECT * FROM message WHERE run_id={run}
    alt msgs пусто
        W->>W: run.state=DONE, stats={...:0}
    else
        W->>LLM: message-filter (батчи по 30) -> relevant true/false
        W->>W: UPDATE message.relevant
        W->>LLM: news-maker (все relevant, cap 100) -> [{title, content, message_indices}]
        W->>W: INSERT news(sources = uniq url группы)
        W->>W: run.state=DONE, finished_at, stats={collected, relevant, news}
    end

    FE->>BE: GET /api/runs/{id}  (polling каждые 2 c)
    BE-->>FE: Run{DONE, news[...]}
```

### Redis-ключи

| Ключ | Тип | Назначение |
|---|---|---|
| `q:extract`, `q:compose` | list | очереди задач (`BRPOP`) |
| `claim:{job_id}` | string, `SET NX EX 600` | «взято в работу» — параллельные worker'ы и повторные enqueue не дублируют обработку |
| `run:{run_id}:pending` | integer, `DECR` | сколько extract-задач осталось; последний инициирует `compose` |

`job_id`: `"{run_id}:{source_id}"` для extract, `"compose:{run_id}"` для compose.

### Отказоустойчивость (light-уровень)

- worker умер посреди задачи → `claim:{job_id}` истекает через TTL, задачу можно перезапустить;
- «завис» Run (в `STARTED` дольше N минут) → кнопка «Повторить» на фронте создаёт новый Run;
- ошибка LLM/парсинга в compose → `run.state=FAILED`, `stats.error`, новости не создаются.

---

## 5. Обработка (LLM)

Провайдер за абстракцией `app/llm/provider.py` — два метода: `filter_relevance(topic, extra, texts)`
и `make_news(topic, messages)`. `LLM_PROVIDER = openai_compat | mock`.
`openai_compat` рассчитан на OpenAI-совместимые API (OpenRouter: `LLM_BASE_URL=https://openrouter.ai/api/v1`,
`LLM_MODEL=openai/gpt-4o-mini`); запрос — `response_format: {"type":"json_object"}` + починка JSON
с ретраем. Оффлайн-демо — на `mock`.

### message-filter (батч ~30 сообщений)

```
system: Ты фильтр релевантности для мониторинга темы «{topic}».
        Дополнительные указания пользователя: {filters[].prompt, через "; "}.
        Для каждого сообщения верни relevant: true|false. Только JSON.
user:   [{"i":0,"text":"..."}, {"i":1,"text":"..."}, ...]
schema: {"results":[{"i":int,"relevant":bool}]}
```

`mock`: `relevant = любая лемма из topic присутствует в тексте` (pymorphy3).

### news-maker (один вызов на Run, relevant с обрезкой до 100 свежих)

```
system: Сгруппируй сообщения об одном и том же событии и сделай из каждой группы новость.
        Тема мониторинга: «{topic}». Заголовок — короткий, content — 3–5 предложений по сути.
        Только JSON.
user:   [{"i":0,"channel":"...","text":"..."}, ...]
schema: {"news":[{"title":str,"content":str,"message_indices":[int]}]}
```

Ответ обёрнут в объект (`{"news":[...]}`), т.к. `response_format: json_object` не допускает голый
массив. `url` в запрос не передаём — восстанавливаем по индексу `i` при записи.
`News.sources` = уникальные `url` сообщений группы.
`mock`: группировка по совпадению первых 4 слов сообщения; `content` = самое длинное сообщение
группы (обрезка до 800 символов).

---

## 6. REST API (зеркало `x.proto`)

Базовый префикс `/api`. UUID — строки. Ошибки — `{ "detail": "..." }`.

| proto RPC | HTTP | Запрос → ответ |
|---|---|---|
| `CreateProject` | `POST /api/projects` | `{name, topic, filters:[{prompt}], sources:[{type:"telegram", telegram}]}` → `Project` |
| `ListProjects` | `GET /api/projects` | → `Project[]` |
| `GetProject` | `GET /api/projects/{id}` | → `Project` |
| `UpdateProject` | `PATCH /api/projects/{id}` | частичный объект → `Project` |
| `DeleteProject` | `DELETE /api/projects/{id}` | → `204` |
| `StartRun` | `POST /api/projects/{id}/runs` | → `Run` (`state=STARTED`, `news=[]`) |
| `GetRun` | `GET /api/runs/{id}` | → `Run` (`news[]` при `DONE`) |
| `ListRuns` | `GET /api/projects/{id}/runs` | → `Run[]` (без `news`) |

```jsonc
// Project
{ "id":"uuid", "name":"...", "topic":"...",
  "filters":[{"id":"uuid","prompt":"..."}],
  "sources":[{"id":"uuid","type":"telegram","telegram":"@channel"}],
  "created_at":"...", "updated_at":"..." }

// Run
{ "id":"uuid", "project_id":"uuid", "state":"STARTED|DONE|FAILED",
  "created_at":"...", "finished_at":null,
  "stats":{"collected":42,"relevant":18,"news":6},
  "news":[ {"title":"...","content":"...","sources":["https://t.me/ch/123"]} ] }
```

Pydantic-схемы вручную зеркалят proto-сообщения (генерацию из proto не подключаем).

---

## 7. Frontend (3 экрана)

| Путь | Экран | Содержимое |
|---|---|---|
| `/` | **Projects** | список проектов + форма создания: `name`, `topic`, повторяемые поля «текстовый фильтр» и «Telegram-канал» |
| `/projects/:id` | **Project** | данные проекта; кнопка «Запустить обновление» → `POST …/runs` → polling `GET /api/runs/{id}` каждые 2 c; плашка `stats`; лента карточек `News` (`title`, `content`, ссылки-источники) |
| `/projects/:id/runs` | **Runs** | история запусков со `state` и `stats` |

Стек: React + Vite + TS, TanStack Query (polling), Mantine.

---

## 8. Конфигурация (ENV)

| Переменная | Default | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://app:app@postgres:5432/app` | Postgres |
| `REDIS_URL` | `redis://redis:6379/0` | Redis |
| `LLM_PROVIDER` | `mock` | `openai_compat` \| `mock` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | — | для `openai_compat` |
| `TG_FETCH_LIMIT` | `100` | максимум постов на канал за Run |
| `TG_FETCH_DAYS` | `7` | глубина чтения канала |
| `FILTER_BATCH` | `30` | размер батча message-filter |
| `NEWSMAKER_CAP` | `100` | максимум relevant-сообщений в news-maker |
| `CORS_ORIGINS` | `http://localhost` | адрес фронта |

---

## 9. docker-compose

```
services:
  postgres:  image postgres:16, volume, healthcheck pg_isready
  redis:     image redis:7, healthcheck redis-cli ping
  backend:   build ./apps/api, cmd uvicorn app.main:app --host 0.0.0.0 --port 8000
             depends_on: postgres(healthy), redis(healthy)
  worker:    build ./apps/api, cmd python -m app.worker.loop
             depends_on: postgres(healthy), redis(healthy)
  nginx:     build ./apps/web (multi-stage: node build -> nginx со статикой + nginx.conf)
             ports 80:80, depends_on: backend
```

`nginx.conf`: `location / { try_files $uri /index.html; }`, `location /api/ { proxy_pass http://backend:8000; }`.

---

## 10. Приложение: исправленный `x.proto`

Проблемы исходного файла:

- нет типа `uuid` в proto3 → `string id` с комментарием `// UUID`;
- `message Run { ... repeated News = 2; ... }` — у поля нет имени → `repeated News news = 2`;
- `message GetRunRequest { uuid = 1; }` — нет имени и типа → `string id = 1`;
- отсутствуют `GetProjectRequest`, `ListProjectsRequest`, `ListProjectsResponse`,
  `UpdateProjectRequest`, `DeleteProjectRequest`, `ListRunsResponse` (упомянуты в сервисах);
- `ProjectFilter.promt` → `prompt`;
- в proto3 у enum обязателен нулевой элемент → `*_UNSPECIFIED = 0`;
- `RunState` без `FAILED`;
- импортируются, но не используются `duration`, `empty` (кроме `DeleteProject`), `field_mask`
  (используем в `UpdateProjectRequest`).

Рабочая версия — в [`../x.proto`](../x.proto) (файл приведён к этому виду):

```proto
syntax = "proto3";
package monitoring.v1;

import "google/protobuf/timestamp.proto";
import "google/protobuf/empty.proto";
import "google/protobuf/field_mask.proto";

option go_package = "gen/monitoring/v1;monitoringv1";

// ---------- Общее ----------

enum SourceType {
  SOURCE_TYPE_UNSPECIFIED = 0;
  SOURCE_TYPE_TELEGRAM = 1;
}

enum RunState {
  RUN_STATE_UNSPECIFIED = 0;
  RUN_STATE_STARTED = 1;
  RUN_STATE_DONE = 2;
  RUN_STATE_FAILED = 3;
}

message ProjectFilter {
  string id = 1;      // UUID, пусто при создании
  string prompt = 2;
}

message Source {
  string id = 1;      // UUID, пусто при создании
  SourceType type = 2;
  string telegram = 3; // @channel | t.me/channel | channel
}

message Project {
  string id = 1;      // UUID
  string name = 2;
  string topic = 3;
  repeated ProjectFilter filters = 4;
  repeated Source sources = 5;
  google.protobuf.Timestamp created_at = 6;
  google.protobuf.Timestamp updated_at = 7;
}

message News {
  string title = 1;
  string content = 2;
  repeated string sources = 3; // URL постов-источников
}

message RunStats {
  int32 collected = 1;
  int32 relevant = 2;
  int32 news = 3;
  string error = 4;
}

message Run {
  string id = 1;         // UUID
  string project_id = 2; // UUID
  RunState state = 3;
  google.protobuf.Timestamp created_at = 4;
  google.protobuf.Timestamp finished_at = 5;
  RunStats stats = 6;
  repeated News news = 7;
}

// ---------- Projects ----------

message CreateProjectRequest {
  string name = 1;
  string topic = 2;
  repeated ProjectFilter filters = 3;
  repeated Source sources = 4;
}
message CreateProjectResponse { Project project = 1; }

message GetProjectRequest { string id = 1; }

message ListProjectsRequest {
  int32 page_size = 1;
  string page_token = 2;
}
message ListProjectsResponse {
  repeated Project projects = 1;
  string next_page_token = 2;
}

message UpdateProjectRequest {
  Project project = 1;
  google.protobuf.FieldMask update_mask = 2;
}

message DeleteProjectRequest { string id = 1; }

// ---------- Runs ----------

message StartRunRequest { string project_id = 1; }
message StartRunResponse { Run run = 1; }

message GetRunRequest { string id = 1; }
message GetRunResponse { Run run = 1; }

message ListRunsRequest {
  string project_id = 1;
  int32 page_size = 2;
  string page_token = 3;
}
message ListRunsResponse {
  repeated Run runs = 1;    // без News
  string next_page_token = 2;
}

// ---------- Сервисы ----------

service ProjectService {
  rpc CreateProject(CreateProjectRequest) returns (CreateProjectResponse);
  rpc GetProject(GetProjectRequest) returns (Project);
  rpc ListProjects(ListProjectsRequest) returns (ListProjectsResponse);
  rpc UpdateProject(UpdateProjectRequest) returns (Project);
  rpc DeleteProject(DeleteProjectRequest) returns (google.protobuf.Empty);
}

service RunService {
  rpc StartRun(StartRunRequest) returns (StartRunResponse);
  rpc GetRun(GetRunRequest) returns (GetRunResponse);
  rpc ListRuns(ListRunsRequest) returns (ListRunsResponse);
}
```

---

## 11. Критерии приёмки

- [ ] `docker compose up --build` поднимает `nginx, backend, worker, postgres, redis`;
      `GET /api/health` = 200 и показывает `db/redis/llm_provider`.
- [ ] `POST /api/projects` с 2 публичными Telegram-каналами и 1 текстовым фильтром → `200` + `id`.
- [ ] `POST /api/projects/{id}/runs` → `Run{state:STARTED}`; в логах worker'а — extract по каждому каналу.
- [ ] Polling `GET /api/runs/{id}` → `state:DONE`, `news[]` непустой, у новостей заполнен `sources`,
      `stats={collected,relevant,news}`.
- [ ] Повторный `POST …/runs` обрабатывает только новые сообщения (курсор `last_msg_id` + `content_hash`),
      дублей в `message` нет.
- [ ] `LLM_PROVIDER=mock` — весь путь работает без сети.
- [ ] `docker compose up --scale worker=2` — одна задача не берётся дважды
      (`claim:{job_id}` + `run:{id}:pending`).
- [ ] Frontend: создание проекта, запуск Run с polling, отображение новостей и истории Run.
