# Руководство для разработчиков

Этот документ описывает, как развернуть проект локально и начать работу.

## 📋 Предварительные требования

Перед началом работы убедитесь, что на вашем компьютере установлены:

| Инструмент | Проверка | Установка (Ubuntu) |
|------------|----------|-------------------|
| Python 3.11+ | `python3 --version` | `sudo apt install python3 python3-venv` |
| Docker + compose | `docker compose version` | [docs.docker.com](https://docs.docker.com/engine/install/) |
| git | `git --version` | `sudo apt install git` |

`protoc` и Node.js на хосте **не нужны**: `make generate` гоняет TypeScript-генерацию в
контейнере `node:20-alpine`, Python-часть — в локальном `.venv` (создаётся `make venv`).
`buf` нужен только для `make lint`/`buf breaking` — опционально (см. ниже).

### Установка buf

```bash
mkdir -p ~/bin
curl -sSL "https://github.com/bufbuild/buf/releases/latest/download/buf-Linux-x86_64" -o ~/bin/buf
chmod +x ~/bin/buf
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
buf --version  # должно показать 1.50+
```

---

## 🚀 Первый запуск

### 1. Клонируйте репозиторий

```bash
git clone <URL_репозитория>
cd ai_product_hack
```

### 2. Установите зависимости

Одна команда — всё будет сделано автоматически:

```bash
make install
```

Эта команда:
- Создаст виртуальное окружение `.venv/`
- Установит Python-пакеты (`grpcio-tools`, `protobuf`)
- Установит JS-плагины (`protoc-gen-es`, `protoc-gen-connect-es`) в `frontend/node_modules/`

### 3. Сгенерируйте код из proto

```bash
make generate
```

После этого появятся:
- `backend/gen/monitoring/v1/monitoring_pb2.py` — Python классы сообщений
- `backend/gen/monitoring/v1/monitoring_pb2_grpc.py` — Python gRPC сервисы
- `frontend/src/gen/monitoring/v1/monitoring_pb.ts` — TypeScript типы
- `frontend/src/gen/monitoring/v1/monitoring_connect.ts` — TypeScript клиенты

### 4. Проверьте что proto-файлы валидны

```bash
make lint
```

✅ Готово! Можно приступать к разработке.

---

## 📁 Структура проекта

```
.
├── proto/monitoring/v1/monitoring.proto   # Источник правды
├── backend/
│   ├── gen/                        # Сгенерированный Python код (коммитится)
│   ├── app/                        # Код бэкенда (пишите здесь)
│   └── migrations/                 # Alembic
├── frontend/
│   ├── node_modules/               # JS зависимости (не коммитится)
│   └── src/
│       ├── gen/                    # Сгенерированный TS код (коммитится)
│       ├── api/client.ts           # Connect-клиенты
│       └── pages/                  # Код фронтенда (пишите здесь)
├── .venv/                          # Python виртуальное окружение (не коммитится)
├── docker-compose.yml              # Стек: postgres, redis, backend, worker, frontend
├── buf.yaml                        # Конфигурация linting для buf
├── Makefile                        # Команды автоматизации
├── CONTRIBUTING.md                 # Этот файл
└── README.md
```

**Про сгенерированный код.** `backend/gen/` и `frontend/src/gen/` **коммитятся** — иначе
`docker compose build` не соберётся без предварительного `make generate` (Dockerfile копирует
`gen/` из контекста сборки). После правки `.proto` перегенерируйте и коммитьте вместе с ним.
`node_modules/` и `.venv/` в git не попадают.

---

## 🚀 Запуск приложения

```bash
make up          # весь стек; первая сборка фронта ~5-8 мин (npm install)
make migrate     # применить миграции
```

Открыть **http://localhost**. Проверка: `curl localhost/api/health`.

Во время работы над бэкендом фронт можно не поднимать:

```bash
make dev         # postgres + redis + backend + worker
make logs        # логи воркера (make logs s=backend)
make down        # остановить
```

`backend` запущен с `--reload`, воркер — нет: после правок в `app/worker`, `app/llm`,
`app/ingestion` выполните `docker compose up -d worker`.

По умолчанию LLM работает в режиме `mock` (без сети). Ключ RouterAI кладётся в `.env`
(см. `.env.example`), `.env` в git не попадает.

---

## 🔄 Рабочий процесс

### Изменение API

1. Отредактируйте `proto/monitoring/v1/monitoring.proto`
2. Проверьте валидность:
   ```bash
   make lint
   ```
3. Перегенерируйте код:
   ```bash
   make generate
   ```
4. `buf breaking --against '.git#branch=main'` — убедитесь, что изменения аддитивные
5. Обновите реализацию в `backend/app/` и `frontend/src/` в соответствии с новыми типами
6. Закоммитьте `.proto`, **сгенерированный код** (`backend/gen/`, `frontend/src/gen/`) и вашу
   реализацию — вместе. Образ не соберётся без сгенерированного кода в репозитории.

Контракт реально управляет обеими сторонами: бэкенд парсит запрос с
`ignore_unknown_fields=False` (поле вне proto → `400 invalid_argument`), фронт типизирован
сгенерированным клиентом (поле вне proto → ошибка `tsc`). Тест `backend/tests/test_contract.py`
проверяет это как свойство.

### Все команды

```bash
make help          # Показать список команд
make install       # Установить все зависимости (однократно)
make lint          # Проверить proto файлы на соответствие стандартам
make generate      # Сгенерировать Python + TypeScript код из proto
make format        # Автоматически отформатировать proto файлы
make clean         # Удалить сгенерированные файлы
make proto-all     # Проверить и сгенерировать (lint + generate)
```

---

## 🐛 Частые проблемы

### `buf: command not found`

Установите `buf` по инструкции выше (раздел "Установка buf").

### `make install` падает с ошибкой `externally-managed-environment`

Это значит вы пытаетесь запустить `pip install` без виртуального окружения. `make install` сам создаёт `.venv/` — просто запустите команду заново. Если проблема сохраняется:
```bash
rm -rf .venv
make install
```

### `make generate` падает на TypeScript генерации

TS-генерация идёт в контейнере `node:20-alpine` и берёт плагины из `frontend/node_modules/`.
Если их там нет — сначала `make install` (ставит плагины через контейнер), затем `make generate`.
Docker при этом обязан быть запущен.

### После `git pull` что-то не работает

Скорее всего изменился `proto`-файл. Просто перегенерируйте код:
```bash
make generate
```

Если менялись зависимости — переустановите их:
```bash
make install
make generate
```

---

## ✅ Чеклист перед коммитом

- [ ] Я не правил(а) файлы в `backend/gen/` и `frontend/src/gen/` руками
- [ ] Если менял(а) `.proto` — выполнил(а) `make generate` и закоммитил(а) результат **вместе** с `.proto`
- [ ] `buf breaking` не ругается (изменения контракта аддитивные)
- [ ] `make test` проходит без ошибок (юнит-тесты на чистой логике, без Docker-сети)
- [ ] Для изменений в worker/API/ingestion — `make smoke` зелёный
- [ ] `docker compose down -v && make up && make migrate` поднимает стек с нуля

---

## 💬 Вопросы?

Если что-то не работает или непонятно — пишите в чат команды. Мы поможем!
