# Руководство для разработчиков

Этот документ описывает, как развернуть проект локально и начать работу.

## 📋 Предварительные требования

Перед началом работы убедитесь, что на вашем компьютере установлены:

| Инструмент | Проверка | Установка (Ubuntu) |
|------------|----------|-------------------|
| Python 3.8+ | `python3 --version` | `sudo apt install python3 python3-venv` |
| pip | `python3 -m pip --version` | `sudo apt install python3-pip` |
| make | `make --version` | `sudo apt install make` |
| buf | `buf --version` | см. ниже |
| protoc | `protoc --version` | `sudo apt install protobuf-compiler` |
| Node.js + npm | `node --version && npm --version` | `sudo apt install nodejs npm` |
| git | `git --version` | `sudo apt install git` |

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
4. Обновите реализацию в `backend/app/` и `frontend/src/` в соответствии с новыми типами
5. Закоммитьте только изменения в `*.proto` и ваш код (не сгенерированные файлы)

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

### `protoc: command not found` при `make generate`

Установите системный `protoc`:
```bash
sudo apt install protobuf-compiler
```

### `make generate` падает на TypeScript генерации

Проверьте что JS плагины установлены:
```bash
ls frontend/node_modules/.bin/protoc-gen-es
```
Если файла нет:
```bash
cd frontend
npm install --save-dev @bufbuild/protoc-gen-es @connectrpc/protoc-gen-connect-es
```

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
- [ ] Если менял(а) `.proto` — выполнил(а) `make generate` и закоммитил(а) результат
- [ ] Я изменил(а) `proto`-файл, если менял(а) API
- [ ] `make lint` проходит без ошибок
- [ ] `make generate` работает без ошибок
- [ ] `make test` проходит без ошибок (юнит-тесты на чистой логике, без Docker-сети)
- [ ] Мой код работает локально; для изменений в worker/API — `make smoke` зелёный

---

## 💬 Вопросы?

Если что-то не работает или непонятно — пишите в чат команды. Мы поможем!
