# System Design

> **Актуальный инженерный дизайн системы.** Вводные и требования: [`REQUIREMENTS.md`](./REQUIREMENTS.md).
> Контракт данных — источник правды: [`../proto/monitoring/v1/monitoring.proto`](../proto/monitoring/v1/monitoring.proto).
> Первая (Telegram-only) версия описана в [`SYSTEM_DESIGN_LIGHT.md`](./SYSTEM_DESIGN_LIGHT.md) —
> она оставлена как история, ссылаться при разработке нужно на этот документ.

**Как читать пометки статуса:**

| Пометка | Значение |
|---|---|
| ✅ | реализовано и проверено вживую |
| ⏭ | сознательно вне скоупа, см. §13 «Путь наращивания» |

Заход по чек-листу организаторов (источники → обогащение → редактирование → дашборд) выполнен
и проверен вживую. §10 «Что было дописано в контракт» — журнал изменений по заходам.

---

## Содержание

1. [Обзор и границы](#1-обзор-и-границы)
2. [Топология развёртывания](#2-топология-развёртывания)
3. [Модель данных (Postgres)](#3-модель-данных-postgres)
4. [Жизненный цикл Run](#4-жизненный-цикл-run)
5. [Источники (ingestion)](#5-источники-ingestion)
6. [Обработка (LLM)](#6-обработка-llm)
7. [API — Connect-RPC из proto](#7-api--connect-rpc-из-proto)
8. [Frontend](#8-frontend)
9. [Конфигурация и docker-compose](#9-конфигурация-и-docker-compose)
10. [Контракт и кодогенерация](#10-контракт-и-кодогенерация)
11. [Критерии приёмки](#11-критерии-приёмки)
12. [Как запускать](#12-как-запускать)
13. [Путь наращивания](#13-путь-наращивания)

---

## 1. Обзор и границы

Пользователь заводит **проект мониторинга** (тема + текстовые фильтры + источники), запускает
обновление и получает ленту новостей: система собирает материалы из источников разных типов,
отсеивает нерелевантное, схлопывает сообщения об одном событии в одну карточку, пишет саммари
и проставляет категорию, важность и сущности. Карточку можно отредактировать, скрыть или
добавить руками; по ленте работают фильтры и поиск.

**Ключевые принципы**

1. **Контракт — источник правды.** Всё, что пересекает провод, описано в
   `proto/monitoring/v1/monitoring.proto`; типы для бэкенда и фронтенда генерируются из него.
   Поле вне контракта отбивается бэкендом (`400 invalid_argument`) и не компилируется на фронте
   (`tsc`). Подробно — §10.
2. **«Что это» отделено от «насколько это интересно».** «Что это» (саммари, категория, важность,
   сущности) считает LLM — дорого и один раз на карточку. «Насколько интересно» (фильтры ленты,
   поиск) — дешёвые операции над готовыми карточками, без обращения к LLM.
3. **Правки пользователя не затираются.** Каждый Run создаёт новые строки `news`, а не
   переписывает существующие, поэтому отредактированная руками карточка не может быть молча
   перегенерирована (решение Р11 из `REQUIREMENTS.md`).
4. **Данные не теряются.** «Удаление» новости и источника — это скрытие (`hidden` / `disabled`),
   строки остаются в БД.
5. **Оффлайн-режим первого класса.** `LLM_PROVIDER=mock` даёт весь сквозной путь без сети и
   ключей — демо не зависит от доступности внешнего API.

**Границы**

| В скоупе | Вне скоупа (и почему) |
|---|---|
| Источники: Telegram + RSS (СМИ и регуляторы) | Скрейпинг произвольных HTML-сайтов регуляторов ⏭ — хрупко; регуляторы, которые нужны для демо, отдают RSS |
| Категория / важность / тип / сущности от LLM | Движок правил ранжирования `field`/`semantic` ⏭ — чек-лист требует *показывать* приоритет, а не давать настраивать веса; §13 |
| Дедупликация событий LLM-группировкой | Эмбеддинги + кластеризация ⏭ — LLM-группировка уже даёт кросс-источниковое схлопывание (решение Р3) |
| Фильтры ленты + текстовый поиск | Полнотекстовый поиск на FTS/`tsvector` ⏭ — на объёме демо `ILIKE` достаточно |
| Ручной запуск обновления | Расписание/APScheduler ⏭ — §13 |
| | Аутентификация, многопользовательский режим, промышленная нагрузка — явно вне скоупа хакатона (`REQUIREMENTS.md` §1) |

---

## 2. Топология развёртывания

```mermaid
flowchart LR
    U[Браузер] --> NGINX[nginx]
    NGINX -->|/| REACT[React static]
    NGINX -->|/api| BE[backend<br/>FastAPI + Connect-RPC]
    BE -->|INSERT tasks| PG[(Postgres<br/>данные + очередь задач)]
    W[worker<br/>поллинг tasks] --> PG
    W -->|claim + heartbeat| RD[(Redis<br/>только SET NX EX)]
    W -->|t.me/s/&lt;channel&gt;| TG[Telegram web preview]
    W -->|RSS/Atom| RSS[Ленты СМИ и регуляторов]
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

**Очередь задач — в Postgres, Redis только под локи.** Воркер поллит таблицу `tasks`, а не
блокируется на чтении из Redis. Redis отвечает ровно за два вопроса: «кто из воркеров исполняет
эту задачу» (`claim`) и «жив ли воркер» (`heartbeat`). Потеря Redis между прогонами не теряет
данных.

---

## 3. Модель данных (Postgres)

```mermaid
erDiagram
    PROJECTS ||--o{ RUNS : ""
    PROJECTS ||--o{ NEWS : ""
    PROJECTS ||--o{ MESSAGES : ""
    PROJECTS ||--o{ SOURCE_CURSORS : ""
    RUNS     ||--o{ MESSAGES : ""
    RUNS     ||--o{ NEWS : ""
    RUNS     ||--o{ TASKS : ""
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
  sources JSONB NOT NULL DEFAULT '[]',   -- список monitoring.v1.Source в proto3-JSON
  collection_days INTEGER NOT NULL DEFAULT 7, -- глубина ПЕРВОГО сбора источника (дальше — курсор);
                                             -- 0 трактуется как 7, диапазон 1..60
  profile TEXT NOT NULL DEFAULT ''            -- профиль бизнеса-заказчика; уходит в промпт
                                             -- саммаризации, важность считается по влиянию на него
);

CREATE TABLE runs (
  id VARCHAR PRIMARY KEY,
  project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  state VARCHAR(50) NOT NULL DEFAULT 'RUN_STATE_STARTED',  -- имя значения enum RunState
  created_at TIMESTAMP NOT NULL,
  stats JSONB NOT NULL DEFAULT '{}'      -- форма monitoring.v1.RunStats; во время обработки
                                        -- несёт ещё stage / stage_done / stage_total (прогресс)
);

-- Карточка события. project_id денормализован (лента строится по проекту, а ручная
-- карточка вообще без Run); category/importance/doc_type — строки с именем enum, как Run.state.
CREATE TABLE news (
  id SERIAL PRIMARY KEY,
  project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_id VARCHAR REFERENCES runs(id) ON DELETE CASCADE,   -- NULL у карточек, добавленных руками
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  sources JSONB NOT NULL DEFAULT '[]',   -- ["https://t.me/ch/123", ...]
  category   VARCHAR(40) NOT NULL DEFAULT 'NEWS_CATEGORY_UNSPECIFIED',    -- имя значения enum
  importance VARCHAR(40) NOT NULL DEFAULT 'NEWS_IMPORTANCE_UNSPECIFIED',
  doc_type   VARCHAR(30) NOT NULL DEFAULT 'DOC_TYPE_UNSPECIFIED',       
  entities JSONB NOT NULL DEFAULT '{}',  -- форма monitoring.v1.NewsEntities
  tags     JSONB NOT NULL DEFAULT '[]',
  hidden BOOLEAN NOT NULL DEFAULT false, -- скрыто из ленты, но не удалено
  created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX ix_news_project_id ON news (project_id);  -- лента строится по проекту, не по Run

-- Ниже — служебные таблицы, наружу в proto не выходят.

-- channel -> source_key (обобщение под RSS), tg_msg_id становится NULLABLE: одна таблица обслуживает
-- и Telegram (source_key = канал), и RSS (source_key = URL ленты).
CREATE TABLE messages (
  id SERIAL PRIMARY KEY,
  project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_id     VARCHAR NOT NULL REFERENCES runs(id)     ON DELETE CASCADE,
  source_key VARCHAR(255) NOT NULL,      -- было channel
  tg_msg_id BIGINT,                      -- было NOT NULL; NULL для RSS
  url TEXT NOT NULL,
  text TEXT NOT NULL,
  posted_at TIMESTAMP,
  content_hash VARCHAR(64) NOT NULL,
  relevant BOOLEAN,                      -- NULL до message-filter
  CONSTRAINT uq_messages_hash UNIQUE (project_id, content_hash)   -- кросс-Run дедуп
);

CREATE TABLE source_cursors (
  project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_key VARCHAR(255) NOT NULL,      -- было channel
  last_msg_id BIGINT,                    -- курсор Telegram
  last_published_at TIMESTAMP,           -- курсор RSS (у записей нет сквозного id)
  PRIMARY KEY (project_id, source_key)
);

-- Очередь воркера. SELECT ... WHERE status='pending' не блокирует строку — несколько
-- воркеров могут выбрать одну и ту же задачу в одном тике поллинга; кто её реально
-- исполняет, решает Redis claim() (единственное, для чего Redis остался в системе).
CREATE TABLE tasks (
  id VARCHAR PRIMARY KEY,
  run_id VARCHAR NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  kind VARCHAR(20) NOT NULL,             -- extract | compose
  payload JSONB NOT NULL DEFAULT '{}',   -- {"project_id","source_type","source_key","collection_days"} для extract
  status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | done
  created_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_tasks_run_id ON tasks(run_id);
CREATE INDEX ix_tasks_created_at ON tasks(created_at);
-- не больше одной compose-задачи на run, даже если несколько extract-задач
-- прогона завершились почти одновременно в разных транзакциях
CREATE UNIQUE INDEX uq_tasks_compose_per_run ON tasks(run_id) WHERE kind = 'compose';
```

**Почему `filters`/`sources`/`entities`/`tags` — JSONB, а `category`/`importance` — строки.**
JSONB хранит вложенные структуры ровно в форме proto3-JSON соответствующих сообщений, поэтому
конвертация в `services/mappers.py` — это `ParseDict`/`MessageToDict`, без ручного перекладывания
полей. Enum'ы же лежат отдельными строковыми колонками с именем значения (`Run.state` так работает
с самого начала): так `WHERE category IN (...)` в фильтрах ленты остаётся обычным индексируемым
условием, а не разбором JSON.

**Почему `news.project_id`, а не только `run_id`.** Лента и фильтры (§7) работают по проекту, а не
по одному прогону; плюс карточка, добавленная руками, вообще не принадлежит никакому Run.
Денормализованный `project_id` закрывает оба случая одной колонкой.

---

## 4. Жизненный цикл Run

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant BE as backend
    participant RD as Redis
    participant W as worker
    participant SRC as t.me/s/ и RSS
    participant LLM as LLM

    FE->>BE: POST /api/monitoring.v1.RunService/StartRun
    BE->>BE: INSERT runs(state=RUN_STATE_STARTED)
    loop по каждому активному источнику проекта
        BE->>BE: INSERT tasks(kind=extract, payload={project,source_type,source_key,collection_days})
    end
    BE-->>FE: StartRunResponse{run}

    loop worker: раз в 2с SELECT tasks WHERE status='pending' LIMIT 20
        W->>RD: SET claim:{job_id} NX EX ttl
        alt claim получен
            W->>W: UPDATE tasks SET status='done' (сразу, отдельным коммитом)
            W->>SRC: Telegram: t.me/s/<channel>?before=... | RSS: GET <feed_url>
            SRC-->>W: посты / записи ленты
            W->>W: INSERT messages ON CONFLICT DO NOTHING (project_id, content_hash)
            W->>W: UPSERT source_cursors (last_msg_id либо last_published_at)
            W->>W: SELECT COUNT(*) tasks WHERE run_id=... AND kind='extract' AND status='pending'
            opt счётчик == 0
                W->>W: INSERT tasks(kind=compose) ON CONFLICT DO NOTHING
            end
        end
    end

    W->>W: compose: SELECT * FROM messages WHERE run_id={run}
    alt сообщений нет
        W->>W: runs.state=RUN_STATE_DONE, stats={collected:0,...}
    else
        W->>LLM: message-filter, батчи по FILTER_BATCH -> relevant true/false
        W->>W: run.stats.stage/stage_done обновляется после каждого батча (commit)
        W->>LLM: news-maker, батчи по NEWSMAKER_BATCH -> группы + саммари + обогащение
        W->>W: run.stats.stage/stage_done обновляется после каждого батча (commit)
        W->>W: INSERT news(project_id, sources, category, importance, doc_type, entities)
        W->>W: runs.state=RUN_STATE_DONE, stats={collected, relevant, news}
    end

    FE->>BE: GetRun (polling каждые 2 c) / ListNews (лента с фильтрами)
    BE-->>FE: карточки новостей
```

Ошибка на этапе compose (недоступный LLM, невалидный JSON после ретраев) → `RUN_STATE_FAILED`
и `stats.error`; воркер продолжает работу.

### Redis-ключи

Очередь задач — таблица `tasks` в Postgres (§3), не Redis. Redis хранит только два вида ключей —
оба живут секунды-минуты, поэтому Redis можно полностью потерять между прогонами без потери данных.

| Ключ | Тип | Назначение |
|---|---|---|
| `claim:{job_id}` | string, `SET NX EX ttl` | «взято в работу» — несколько воркеров могут выбрать одну и ту же pending-строку из `tasks` (обычный `SELECT`, без блокировки); claim решает, кто её реально исполняет. `ttl` = `CLAIM_TTL_EXTRACT` (600с) или `CLAIM_TTL_COMPOSE` (1800с) |
| `worker:heartbeat` | string, `SET EX 20` (`HEARTBEAT_TTL`) | обновляется отдельной фоновой задачей `_heartbeat` раз в 5 с (`HEARTBEAT_INTERVAL`), независимо от того, какую задачу крутит воркер; `/api/health` считает воркер живым, пока ключ не истёк |

`job_id`: `"{run_id}:{source_key}"` для extract, `"compose:{run_id}"` для compose.

### Отказоустойчивость

- воркер умер посреди задачи → `claim` истекает по TTL, задача осталась в Postgres и будет
  подобрана снова (кроме доли секунды между claim и `UPDATE status='done'`);
- Redis целиком недоступен → `/api/health` покажет `degraded`, но очередь (`tasks`) не теряется —
  обработка продолжится, как только Redis вернётся;
- один источник недоступен (канал без веб-превью, отвалившаяся лента) → ошибка изолирована в его
  extract-задаче: `msgs = []`, предупреждение в лог, остальные источники прогона отрабатывают;
- «завис» Run → фронт показывает баннер с кнопкой перезапуска. Детекция по остановке
  прогресса, а не по таймеру: прогресс (`RunStats.stage_done`) не двигался ~4 мин, либо
  обработка так и не дошла до первого этапа за ~3 мин;
- ошибка LLM в compose → `RUN_STATE_FAILED`, `stats.error`, новости не создаются;
- сетевая ошибка/429/5xx к LLM → ретрай с экспоненциальной паузой (1/2/4 с), отдельно от ретрая
  на невалидный JSON;
- `DeleteProject` во время активного прогона → Postgres ловит дедлок (каскадное удаление
  vs `UPDATE runs` из compose) и снимает одну транзакцию; воркер ловит исключение, пишет в
  лог и продолжает следующий тик. Затронутый прогон остаётся в `RUN_STATE_STARTED`, но его
  проект уже удалён.
- **Дрейф часов WSL2-VM** (окружение разработки): часы контейнеров периодически скачут на ~1ч
  и назад. Redis-ключ `worker:heartbeat` с TTL при скачке вперёд немедленно «протухает» →
  `/api/health` кратко показывает `worker: false`, хотя воркер жив. Не баг кода, лечится
  `wsl --shutdown` из Windows. **UI на это не завязан** — баннер «обработка застряла» на
  фронте срабатывает по остановке прогресса (`RunStats.stage_done` не двигается несколько
  минут), а не по `/api/health`.

---

## 5. Источники (ingestion)

Каждый источник в проекте — это `monitoring.v1.Source` (§10). Тип определяет коннектор,
`source_key` — ключ курсора и дедупа:

| Тип | `source_key` | Коннектор | Курсор |
|---|---|---|---|
| `SOURCE_TYPE_TELEGRAM` ✅ | имя канала (`cit_gov`) | `app/ingestion/telegram_web.py` — публичное веб-превью `t.me/s/<channel>`, без ключей и авторизации, пагинация `?before=<id>` | `last_msg_id` |
| `SOURCE_TYPE_RSS` ✅ | URL ленты | `app/ingestion/rss.py` — `httpx` + `feedparser`, HTML в описании чистится `selectolax` | `last_published_at` |

Оба коннектора возвращают однородный список записей с полями `url`, `text`, `posted_at`,
`content_hash`; дальше конвейер не различает, откуда материал пришёл. Дедупликация —
`UNIQUE(project_id, content_hash)`: одинаковый текст не обрабатывается повторно ни между
прогонами, ни между источниками (перепечатка одной новости в двух лентах схлопывается).

**Почему RSS покрывает и СМИ, и регуляторов.** Чек-лист требует три категории источников
(СМИ / сайты регуляторов / Telegram). Регуляторы, нужные для демо, публикуют RSS — поэтому
категория источника это *ярлык* (`Source.label`), а не отдельная технология парсинга.
Скрейпинг произвольного HTML регуляторов ⏭ — он хрупок и не нужен для покрытия требования.

**Набор источников для демо** (6 источников, 3 категории). URL проверены **из контейнера**, а не
только с хоста — см. предупреждение ниже:

| Категория | Источник | URL / канал |
|---|---|---|
| СМИ | ТАСС | `https://tass.ru/rss/v2.xml` |
| СМИ | РБК | `https://rssexport.rbc.ru/rbcnews/news/30/full.rss` |
| Регулятор | Правительство РФ | `http://government.ru/all/rss/` |
| Регулятор | ФНС России | `https://www.nalog.gov.ru/rn77/rss/` |
| Telegram | ЦИТ | `cit_gov` |
| Telegram | АРПП «Отечественный софт» | `arppsoft` |

> ⚠️ **Проверять доступность источника нужно из контейнера, а не с хоста.**
> `https://www.cbr.ru/rss/RssPress` (Банк России) отвечает с хоста, но из контейнера TCP-соединение
> до `185.178.208.7:443` уходит в таймаут — DNS при этом резолвится верно. Это ограничение сетевого
> окружения, не код. Поэтому регуляторов в демо представляют Правительство РФ и ФНС (оба — из
> списка регуляторов в самом чек-листе организаторов).
>
> Другие проверенные варианты: Интерфакс (`https://www.interfax.ru/rss.asp`) и Коммерсант
> (`https://www.kommersant.ru/RSS/news.xml`) — рабочие, как запасные СМИ. Не работают из
> контейнера: Роспотребнадзор и Минэкономразвития (таймаут), Госдума (404 на `/news/rss/`),
> Минцифры (200, но без `<item>`). `iz.ru` отдаёт 403 даже с браузерным User-Agent.

---

## 6. Обработка (LLM)

Провайдер за абстракцией `app/llm/provider.py`, `LLM_PROVIDER = openai_compat | mock`.
`openai_compat` рассчитан на OpenAI-совместимые API; используется **RouterAI**
(`LLM_BASE_URL=https://routerai.ru/api/v1`, модель `deepseek/deepseek-v4-flash-0731`).
Оффлайн-демо — на `mock`.

**Форма ответа — три уровня подстраховки** (`_complete_json` в `openai_compat.py`):

1. **strict `response_format: json_schema`** — схема (`_FILTER_SCHEMA` / `_NEWS_SCHEMA`)
   ограничивает модель на генерации: `message_indices` гарантированно массив int,
   `category`/`importance`/`doc_type` — только из `enum`, `entities` — ровно 4 ключа.
2. **откат на `json_object`** — RouterAI проксирует ~490 моделей, и не все умеют `json_schema`
   (`deepseek-v4-flash` через RouterAI — умеет, проверено вживую: лог
   `LLM: strict json_schema поддерживается`). Первый же `400` на схему переводит **весь
   процесс воркера** на `json_object` (`_json_schema_supported = False`) — больше не пробуем.
3. **ленивый парсер + ретрай ×3** — `_loads_lenient` срезает markdown-заборы и вытаскивает
   `{…}`; если 200 пришёл, но JSON всё равно кривой — просим модель починить (до 3 раз).

Плюс `filter_relevance`/`make_news` читают каждое поле терпимо: пропуск или незнакомое
значение → `*_UNSPECIFIED` (перевод в `app/llm/schema.py`), но прогон не падает.
Отдельно — сетевой ретрай на транспортные ошибки и 429/5xx (`_post_with_retry`).

### message-filter (батч `FILTER_BATCH` = 30) ✅

```
system: Ты фильтр релевантности для мониторинга темы «{topic}».
        Дополнительные указания пользователя: {filters[].prompt, через "; "}.
        Для каждого сообщения верни relevant: true|false. Только JSON.
user:   [{"i":0,"text":"..."}, ...]
schema: {"results":[{"i":int,"relevant":bool}]}
```

`mock`: `relevant = любая лемма из topic присутствует в тексте` (pymorphy3).

### news-maker (батчи `NEWSMAKER_BATCH` = 12, вход обрезан до `NEWSMAKER_CAP` свежих) ✅

```
system: Сгруппируй сообщения об одном и том же событии и сделай из каждой группы новость.
        Тема мониторинга: «{topic}». [Профиль бизнеса-заказчика: «{profile}» — если задан.]
        Заголовок — короткий, content — 3–5 предложений по сути.
        Плюс для каждой группы: категория, важность, тип документа и сущности. Только JSON.
        importance: high — прямое влияние на бизнес (НПА, штрафы/суд, кризис, ход прямого
        конкурента); medium — косвенное/отложенное; low — фон. Оценивается по влиянию на профиль.
user:   [{"i":0,"source":"...","text":"..."}, ...]
schema: {"news":[{"title":str, "content":str, "message_indices":[int],
                  "category":"регуляторика|репутация|конкуренты|тренды",
                  "importance":"high|medium|low",
                  "doc_type":"npa|news",
                  "entities":{"who":str,"what":str,"when":str,"consequences":str}}]}
```

Схема ответа соответствует решению Р5 из `REQUIREMENTS.md` — минимальный structured output,
никаких дополнительных флагов.

Ответ обёрнут в объект (`{"news":[...]}`), т.к. `response_format: json_object` не допускает голый
массив. `url` в запрос не передаём — восстанавливаем по индексу `i` при записи.

**Почему батчами.** На входе из ~30 сообщений reasoning-модель тратила 21k reasoning-токенов и
возвращала результат лишь по 1–2 сообщениям. Режем вход на `NEWSMAKER_BATCH` (12), индексы внутри
батча сдвигаем обратно в общий список. Замер на 6 каналах: было `relevant 28 → news 1`, стало
`relevant 29 → news 27`.

**Важность — относительно бизнеса-заказчика.** `Project.profile` (свободный текст: чем
занимается компания, ключевые риски) уходит в системный промпт `make_news`; `importance`
оценивается по влиянию события на этот бизнес, а не по абстрактной значимости. Профиль пуст →
оценка по общей значимости для темы (прод-путь так и работает, пока поле не заполнено). На
размеченном датасете (`app/eval/enrichment.py`) профиль + явная рубрика high/medium/low подняли
accuracy важности ~0.63 → ~0.78.

**Перевод значений LLM в enum'ы контракта** — в одном месте (`app/llm/schema.py`), чтобы
провайдеры говорили на языке предметной области (русские названия категорий, как в чек-листе), а
контракт хранил канонические имена enum'ов. Неизвестное/битое значение → `*_UNSPECIFIED`, а не
падение.

**`entities.when` считается детерминированно:** если LLM вернул непустое значение — берём его
(он может дать более информативное «вступает в силу с 1 марта»), иначе подставляем дату самого
раннего сообщения группы, которая и так известна. Так поле корректно заполняется и на `mock`,
который сущности извлекать не умеет.

**`mock` без сети:** группировка по совпадению первых 4 слов; категория и важность — по
словарям ключевых слов через леммы (pymorphy3), `doc_type=npa` при словах «закон/приказ/
постановление/указ/кодекс», иначе `news`. Грубо, но детерминированно и демонстрируемо офлайн.

---

## 7. API — Connect-RPC из proto

Транспорт: **Connect поверх HTTP/JSON**. Адрес метода складывается из полного имени сервиса
в proto и имени RPC:

```
POST /api/{package}.{Service}/{Method}
Content-Type: application/json
тело      — сообщение Request  в proto3-JSON
200       — сообщение Response в proto3-JSON
ошибка    — HTTP-код + {"code": "...", "message": "..."}
```

| RPC | Назначение | Статус |
|---|---|---|
| `ProjectService.CreateProject` | создать проект (тема, фильтры, источники) | ✅ |
| `ProjectService.GetProject` / `ListProjects` | чтение | ✅ |
| `ProjectService.UpdateProject` | правка полей по `FieldMask`; **управление источниками** идёт сюда: `update_mask: ["sources"]` с новым массивом | ✅ |
| `ProjectService.DeleteProject` | удалить проект (каскадом runs/news/messages/tasks) | ✅ |
| `RunService.StartRun` / `GetRun` / `ListRuns` | запуск обновления и его результат | ✅ |
| `NewsService.ListNews` | **лента проекта с фильтрами и поиском** | ✅ |
| `NewsService.UpdateNews` | правка карточки: заголовок, саммари, категория, важность, теги, скрытие | ✅ |
| `NewsService.CreateNews` | ручное добавление материала | ✅ |

Плюс служебный `GET /api/health` — вне контракта, инфраструктурный (БД, Redis, живость воркера,
реестр зарегистрированных RPC).

Коды ошибок Connect → HTTP: `invalid_argument` 400, `not_found` 404, `failed_precondition` 412,
`unimplemented` 501, `internal` 500.

### Фильтры и поиск (`ListNews`) ✅

Фильтрация идёт по проекту, а не по одному прогону: `project_id` + категории (OR), важности (OR),
источник, диапазон дат, текстовый запрос `q`, флаг `include_hidden` (по умолчанию скрытые не
показываются). Поиск — `ILIKE` по заголовку и тексту; на объёме демо этого достаточно, FTS ⏭.
Пагинация — keyset по `news.id` (`ORDER BY id DESC`, `WHERE id < page_token`).

```jsonc
// CreateProject
{ "name": "ИТ-мониторинг", "topic": "цифровые технологии, гранты",
  "collectionDays": 15,
  "filters": [{"prompt": "не интересны поздравления"}],
  "sources": [{"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov", "label": "ЦИТ"},
              {"type": "SOURCE_TYPE_RSS", "rssUrl": "http://government.ru/all/rss/",
               "label": "Правительство РФ (регулятор)"}] }

// ListNews
{ "projectId": "...", "categories": ["NEWS_CATEGORY_REGULATORY"],
  "importances": ["NEWS_IMPORTANCE_HIGH"], "q": "лицензия", "pageSize": 50 }

// UpdateNews — маска обязательна, иначе «показать скрытую» невыразимо
{ "id": 42, "hidden": false, "updateMask": {"paths": ["hidden"]} }
```

### Где контракт реально проверяется

| Сторона | Механизм | Что происходит при расхождении |
|---|---|---|
| Backend | `json_format.Parse(body, RequestPb(), ignore_unknown_fields=False)` | `400 invalid_argument` с перечислением допустимых полей |
| Backend | `services/mappers.py` — единственное место ORM ↔ protobuf | смена proto ломает сборку сообщения в одном месте |
| Backend | `connect.py` сверяет тип ответа хендлера с объявленным в proto | `500 internal` |
| Frontend | `createPromiseClient(ProjectService, transport)` из `src/gen/` | ошибка `tsc` (`TS2353: ... does not exist in type PartialMessage<...>`) |
| Оба | `make lint` (buf) + `buf breaking` + `make generate` перед коммитом | несогласованный proto не пройдёт review |

Терсность proto3-JSON: поля со значением по умолчанию в ответе опускаются, поэтому `stats` со
всеми нулями приходит как `{}` — сгенерированный клиент подставляет нули сам.

---

## 8. Frontend

| Путь | Экран | Содержимое | Статус |
|---|---|---|---|
| `/` | **Projects** | список проектов + форма создания: `name`, `topic`, период первичного сбора (сутки / 7 / 15 / 30 дней), текстовые фильтры, редактор источников (тип, канал/URL, ярлык, активность) | ✅ |
| `/projects/:id` | **Project** | данные проекта; редактирование источников и периода первичного сбора; «Запустить обновление» → `StartRun` → polling `GetRun` (кнопка заблокирована, пока прогон идёт); во время прогона — подпись этапа и прогресс-бар (`RunStats.stage` / `stage_done` / `stage_total`); плашка `stats`; лента карточек с категорией, важностью, сущностями; правка и скрытие карточки | ✅ |
| `/projects/:id/news` | **Лента (дашборд)** | вся лента проекта с фильтрами (категория, важность, источник, даты) и поиском; ручное добавление материала | ✅ |
| `/projects/:id/runs` | **Runs** | история запусков со `state` и `stats` | ✅ |

Стек: React + Vite + TS, TanStack Query (polling и инвалидация кэша), Mantine.
Клиент — сгенерированный: `src/api/client.ts` создаёт `createConnectTransport({ baseUrl: "/api" })`
и `createPromiseClient(...)`. Типы `Project`, `Run`, `News`, `NewsCategory`, `SourceType` берутся
из `src/gen/`, руками не пишутся.

Если прогресс прогона замер — этап (`RunStats.stage_done`) не двигался ~4 мин, либо обработка
не дошла до первого этапа за ~3 мин — показывается баннер «обработка идёт дольше обычного» с
кнопкой перезапуска, чтобы упавший воркер не выглядел как бесконечный спиннер. Детекция
клиентская, по остановке прогресса, `/api/health` в ней не участвует. ✅

---

## 9. Конфигурация и docker-compose

`backend/app/config.py`, значения по умолчанию — в `.env.example`. Секреты — в `.env` (не в git).

| Переменная | Default | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://app:app@postgres:5432/app` | Postgres. Alembic сам подменяет драйвер на синхронный |
| `REDIS_URL` | `redis://redis:6379/0` | Redis (только локи и heartbeat) |
| `CORS_ORIGINS` | `http://localhost` | адрес фронта |
| `DEBUG` | `false` | уровень логов, echo SQL |
| `LLM_PROVIDER` | `mock` | `openai_compat` \| `mock` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | — | для `openai_compat` (RouterAI) |
| `TG_FETCH_LIMIT` / `TG_FETCH_DAYS` | `100` / `7` | лимит постов и глубина **повторного** чтения Telegram-канала (инкрементальный догон по курсору) |
| `RSS_FETCH_LIMIT` / `RSS_FETCH_DAYS` ✅ | `50` / `7` | то же для RSS-лент |
| `FILTER_BATCH` | `30` | размер батча message-filter |
| `NEWSMAKER_CAP` / `NEWSMAKER_BATCH` | `100` / `12` | вход news-maker: обрезка и размер батча |

Глубину **первого** сбора источника задаёт не ENV, а поле проекта `Project.collection_days`
(мастер создания, пресеты сутки / 7 / 15 / 30 дней) — оно едет в payload extract-задачи.
`*_FETCH_DAYS` применяются, только когда у источника уже есть курсор.

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
поллингом `tasks`, повторный захват отсекается Redis `claim`-ключом.

---

## 10. Контракт и кодогенерация

Источник правды — [`proto/monitoring/v1/monitoring.proto`](../proto/monitoring/v1/monitoring.proto).

```bash
make lint       # buf lint
make generate   # backend/gen/*.py  +  frontend/src/gen/*.ts
make proto-all  # то и другое
buf breaking --against '.git#branch=main'   # доказать, что изменения аддитивные
```

Сгенерированное **коммитится** (`backend/gen/`, `frontend/src/gen/`): `docker compose build`
копирует `gen/` из контекста сборки, иначе образ не соберётся без предварительной генерации.
Правило: изменил `.proto` → `buf lint` → `buf breaking` → `make generate` → коммить вместе.

**Порядок работы над любой фичей**: сначала контракт, потом реализация. Нельзя «пока сделаем в
JSON, а в proto потом занесём» — тогда расхождение сторон перестаёт ловиться на компиляции и
всплывает на демо.

### Что было дописано в контракт под функциональность

Журнал изменений контракта, по заходам.

**Заход 1 — состояние Run и метрика обработки** ✅

```proto
enum RunState {
  ...
  RUN_STATE_FAILED = 3;      // прогон упал (LLM недоступен и т.п.)
}

message RunStats {           // «обработано / релевантно / новостей» для плашки метрики
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

**Заход 2, фаза A — источники разных типов** ✅

```proto
enum SourceType {
  SOURCE_TYPE_UNSPECIFIED = 0;
  SOURCE_TYPE_TELEGRAM = 1;
  SOURCE_TYPE_RSS = 2;       // NEW
}

message Source {
  SourceType type = 1;
  string telegram = 2;
  string rss_url = 3;        // NEW — когда type == SOURCE_TYPE_RSS
  string label = 4;          // NEW — «ЦБ РФ (регулятор)»: категория источника для UI и демо
  bool disabled = 5;         // NEW — источник на паузе, но не удалён
}
```

**Заход 2, фаза B — обогащение карточки** ✅

```proto
enum NewsCategory {          // NEW — категоризация из чек-листа
  NEWS_CATEGORY_UNSPECIFIED = 0;
  NEWS_CATEGORY_REGULATORY = 1;   // регуляторика
  NEWS_CATEGORY_REPUTATION = 2;   // репутация
  NEWS_CATEGORY_COMPETITORS = 3;  // конкуренты
  NEWS_CATEGORY_TRENDS = 4;       // тренды
}
enum NewsImportance {        // NEW — приоритизация
  NEWS_IMPORTANCE_UNSPECIFIED = 0;
  NEWS_IMPORTANCE_HIGH = 1;
  NEWS_IMPORTANCE_MEDIUM = 2;
  NEWS_IMPORTANCE_LOW = 3;
}
enum DocType {               // NEW — НПА или новостная статья
  DOC_TYPE_UNSPECIFIED = 0;
  DOC_TYPE_NEWS = 1;
  DOC_TYPE_NPA = 2;
}
message NewsEntities {       // NEW — кто / что / когда / последствия
  string who = 1;
  string what = 2;
  string when = 3;
  string consequences = 4;
}

message News {
  string title = 1;
  string content = 2;
  repeated string sources = 3;
  int32 id = 4;                                // NEW — без id карточку нельзя адресовать
  string project_id = 5;                        // NEW — лента строится по проекту
  string run_id = 6;                            // NEW — пусто у карточек, добавленных руками
  NewsCategory category = 7;                    // NEW
  NewsImportance importance = 8;                // NEW
  DocType doc_type = 9;                          // NEW
  NewsEntities entities = 10;                    // NEW
  repeated string tags = 11;                     // NEW
  bool hidden = 12;                              // NEW
  google.protobuf.Timestamp created_at = 13;     // NEW
}
```

**Заход 2, фазы C–D — управление данными и лента** ✅

```proto
service NewsService {                          // NEW
  rpc ListNews(ListNewsRequest) returns (ListNewsResponse);      // лента с фильтрами и поиском
  rpc UpdateNews(UpdateNewsRequest) returns (UpdateNewsResponse); // правка и скрытие
  rpc CreateNews(CreateNewsRequest) returns (CreateNewsResponse); // ручное добавление
}

message ListNewsRequest {
  string project_id = 1;
  repeated NewsCategory categories = 2;      // OR-фильтр; пусто = все
  repeated NewsImportance importances = 3;   // OR-фильтр; пусто = все
  string source = 4;                          // точное совпадение с элементом News.sources
  google.protobuf.Timestamp published_from = 5; // не `from` — ключевое слово Python, генератор
  google.protobuf.Timestamp published_to = 6;   //   оставляет его как есть → префикс
  string q = 7;                                // текстовый поиск по title + content
  bool include_hidden = 8;
  int32 page_size = 9;
  string page_token = 10;
}

message UpdateNewsRequest {
  int32 id = 1;
  string title = 2;
  string content = 3;
  NewsCategory category = 4;
  NewsImportance importance = 5;
  repeated string tags = 6;
  bool hidden = 7;
  google.protobuf.FieldMask update_mask = 8;   // обязателен, см. «подводные камни» ниже
}
```

Управления источниками отдельными RPC **нет намеренно**: добавление, правка, удаление и пауза
источника — это `UpdateProject` с `update_mask: ["sources"]` и новым массивом. На масштабе
«несколько источников в проекте» это проще, чем `Source.id` + три отдельных RPC.

**Заход 3 — период сбора на уровне проекта + прогресс обработки** ✅

```proto
message Project {
  ...
  int32 collection_days = 8;   // NEW — глубина ПЕРВОГО сбора источника (дальше — курсор), 1..60
}
message CreateProjectRequest { ...  int32 collection_days = 5; }   // NEW
message UpdateProjectRequest { ...  int32 collection_days = 7; }   // NEW (в UPDATABLE)

message RunStats {
  int32 collected = 1;
  int32 relevant = 2;
  int32 news = 3;
  string error = 4;
  string stage = 5;        // NEW — "filtering" | "composing"; пусто на терминальном состоянии
  int32 stage_done = 6;    // NEW — батч X из ...
  int32 stage_total = 7;   // NEW
}
```

`RunStats` расширен, а не заведено `RunProgress`: `run.stats` уже JSONB, `stats_to_pb` уже
`ParseDict(ignore_unknown_fields=True)` — ноль плюмбинга. Воркер (`handle_compose`) переписывает
`run.stats` после каждого батча filter/news-maker и коммитит — фронт поллит `GetRun` и рисует
полосу. Терминальные ветки пишут stats без `stage`.

Заодно починен heartbeat: `worker/loop.py` трогал ключ только между задачами, а один
LLM-вызов легко идёт >15с → `/api/health` врал `worker: false` весь compose. Теперь пульс —
отдельная фоновая задача (`_heartbeat`, раз в `HEARTBEAT_INTERVAL`=5с, TTL 20с), не зависит
от того, какую задачу воркер крутит.

**Заход 4 — профиль бизнеса-заказчика для оценки важности** ✅

```proto
message Project {
  ...
  string profile = 9;   // NEW — чем занимается бизнес, ключевые риски; уходит в промпт
                          //   саммаризации, importance оценивается по влиянию на этот бизнес
}
message CreateProjectRequest { ...  string profile = 6; }   // NEW
message UpdateProjectRequest { ...  string profile = 8; }   // NEW (в UPDATABLE)
```

Поле provider-метода, а не только контракта: `LLMProvider.make_news(topic, messages, profile="")`.
Прод (`handle_compose`) передаёт `project.profile`; пусто → промпт без блока профиля, поведение
как раньше. Плюс в `_NEWS_SYS` добавлена полная рубрика importance (было определено только
`high`). Измерено на `app/eval/enrichment.py`: importance ~0.63 → ~0.78, category ~0.87 → ~0.90.

### Подводные камни proto3 (найденные в этом проекте)

| Место | Проблема | Решение |
|---|---|---|
| `FilterType.PROMT_BASED = 0` | содержательный ноль: в proto3-JSON нулевое значение опускается, поэтому «не задан» неотличим от «prompt-based» | пока тип фильтра один — безвредно; при появлении второго добавить `FILTER_TYPE_UNSPECIFIED = 0` и сдвинуть остальные (ломающее, поймает `buf breaking`) |
| `Source.disabled`, а не `enabled` | у скаляров proto3 нет presence: пропущенное `enabled` парсится как `false` и молча выключило бы все существующие источники | флаг инвертирован — дефолт `false` означает «источник активен» |
| `UpdateNewsRequest.update_mask` | у `hidden`/`title`/`tags` пустое значение легитимно («показать обратно», «очистить теги»), без маски оно неотличимо от «поле не прислали» | обязательная `FieldMask`, как в `UpdateProjectRequest` |
| Новые enum'ы | — | все начинаются с `*_UNSPECIFIED = 0`, в отличие от легаси `FilterType` |

---

## 11. Критерии приёмки

Построчно против MVP-чек-листа организаторов (`REQUIREMENTS.md` §1).

| Требование чек-листа | Как закрыто | Статус |
|---|---|---|
| Сбор минимум из 5 источников разных типов | 2 RSS СМИ + 1 RSS регулятора + 2 Telegram-канала, §5 | ✅ |
| Три категории источников (СМИ / регуляторы / Telegram) | RSS-коннектор для СМИ и регуляторов, `t.me/s/` для Telegram; категория — `Source.label` | ✅ |
| Автоматическая саммаризация ≥10 материалов | news-maker, 3–5 предложений на карточку, батчами; на демо-проекте — десятки материалов | ✅ |
| Дашборд с фильтрацией и поиском | `NewsService.ListNews` + экран `/projects/:id/news`, §7–8 | ✅ |
| Добавление, редактирование, удаление источников | редактор источников на фронте → `UpdateProject` с маской `sources`; пауза через `disabled` | ✅ |
| Редактирование метаданных и саммари публикаций | `NewsService.UpdateNews` + модалка правки | ✅ |
| Саммари 3–5 предложений + сущности (кто/что/когда/последствия) | схема news-maker по решению Р5, §6 | ✅ |
| Категоризация (регуляторика / репутация / конкуренты / тренды) | `NewsCategory`, заполняется news-maker'ом | ✅ |
| Приоритизация (высокая / средняя / низкая) | `NewsImportance`, отображается бейджем, доступна как фильтр | ✅ |
| Добавление источника по URL | RSS-источник задаётся URL'ом в редакторе источников | ✅ |
| Редактирование заголовка, саммари, категории, приоритета, тегов | `UpdateNews` с `FieldMask` | ✅ |
| Удаление/скрытие источника или публикации | `News.hidden`, `Source.disabled` — скрытие без потери данных | ✅ |
| Ручное добавление материала | `NewsService.CreateNews` (`run_id` пустой) | ✅ |
| Метрика: обработано / релевантно / отсеяно | `RunStats` (`collected`/`relevant`/`news`) на плашке прогона | ✅ |
| Выбор периода первичного сбора (сутки / 7 / 15 дней) | `Project.collection_days`, пресеты в мастере создания и в карточке проекта (§5, §9) | ✅ |

Инженерные проверки:

- [x] `buf lint` чистый, `make generate` воспроизводит `backend/gen` и `frontend/src/gen`
- [x] неизвестное поле в запросе → `400 invalid_argument`; поле вне контракта на фронте → ошибка `tsc`
- [x] `docker compose up` + `alembic upgrade head` поднимают систему с нуля
- [x] `make test` — юнит-тесты без сети и БД (мапперы, mock-LLM, парсеры, контракт)
- [x] `make smoke` — сквозной прогон `CreateProject → StartRun → GetRun == DONE`
- [x] `/api/health` показывает БД, Redis и живость воркера
- [x] `--scale worker=2` не даёт дублей (claim + уникальный индекс на compose-задачу)
- [x] прогон с источниками обоих типов в одном Run (6 источников → 111 материалов)
- [x] карточка с категорией/важностью/сущностями от LLM; правка переживает новый Run
- [x] фильтры и поиск по ленте возвращают корректное подмножество
- [x] строгий `response_format: json_schema` с откатом на `json_object` и ленивым парсером (§6)
- [x] индикатор прогресса: `RunStats.stage`/`stage_done`/`stage_total` пишутся по батчам,
      фронт рисует полосу; баннер «завис» — по остановке прогресса, не по `/api/health`

---

## 12. Как запускать

```bash
make up          # поднять весь стек (первая сборка фронта ~5-8 мин)
make migrate     # применить миграции
make test        # юнит-тесты бэкенда (без Postgres/Redis/сети)
make smoke       # сквозная проверка стека
make logs        # логи воркера (make logs s=backend)
make proto-all   # buf lint + перегенерация после правки proto
```

UI — http://localhost, health — `curl localhost/api/health`.

Реальный LLM вместо `mock` — положить в `.env`:

```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://routerai.ru/api/v1
LLM_API_KEY=<ключ RouterAI>
LLM_MODEL=deepseek/deepseek-v4-flash-0731
docker compose up -d worker    # воркер не перечитывает env на лету
```

**Известные грабли**

- воркер не перечитывает `.env` на лету — после правки `docker compose up -d worker`;
- нет `.env` → тихий откат на `LLM_PROVIDER=mock`; проверять `llm_provider` в `/api/health`;
- часть Telegram-каналов отключает веб-превью (напр. `rian_ru`) — оттуда `extract` вернёт 0
  сообщений с предупреждением в логе;
- после `docker compose restart backend` nginx может отдавать 502, если резолвер закешировал
  старый IP — в `frontend/nginx.conf` для этого стоит `resolver 127.0.0.11` + переменная в
  `proxy_pass`.

---

## 13. Путь наращивания

Осознанно не делаем сейчас — не потому что не нужно, а потому что не входит в чек-лист
организаторов и не помещается в срок. Порядок — по убыванию отдачи:

1. **Движок правил ранжирования** (решения Р6–Р9): позиция карточки = сумма весов сработавших
   правил, правила двух видов — `field` (условия по полям карточки) и `semantic` (близость
   эмбеддинга к эталонному тексту), действия `boost/penalize/pin/hide`, объяснение позиции
   списком сработавших правил, плюс неотключаемые защитные правила «Требует внимания»
   (критичные изменения НПА, комплаенс-риски, репутационные кризисы).
2. **Эмбеддинги + кластеризация событий** вместо LLM-группировки: окно N дней, пороги косинуса
   (`sim ≥ 0.82` — сливать, `0.62…0.82` — сливать при совпадении сущностей), кэш эмбеддинга на
   сообщении. Даст воспроизводимость и независимость от того, как модель сегодня «настроена».
3. **Расписание** в воркере (периодический авто-Run проекта: раз в час / несколько раз в день /
   раз в день), сейчас — только ручной запуск.
4. **Дайджест за период** с экспортом в Markdown.
5. **Полнотекстовый поиск** (Postgres `tsvector` + ранжирование `ts_rank`) вместо `ILIKE`, когда
   объём ленты вырастет настолько, что это станет заметно.
6. **Оффлайн-архив как тип источника** (`SOURCE_TYPE_ARCHIVE`) — набор из 50+ статей и НПА для
   отладки саммаризации без внешних API.
7. **Скрейпинг HTML-сайтов регуляторов** для тех, кто не отдаёт RSS.
