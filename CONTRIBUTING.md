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
├── proto/                          # Исходные .proto файлы (источник правды)
│   └── monitoring/v1/
│       └── monitoring.proto
├── backend/
│   ├── gen/                        # Сгенерированный Python код (не коммитится!)
│   │   └── monitoring/v1/
│   └── app/                        # Код бэкенда (пишите здесь)
├── frontend/
│   ├── node_modules/               # JS зависимости (не коммитится!)
│   └── src/
│       ├── gen/                    # Сгенерированный TS код (не коммитится!)
│       └── ...                     # Код фронтенда (пишите здесь)
├── .venv/                          # Python виртуальное окружение (не коммитится!)
├── buf.yaml                        # Конфигурация linting для buf
├── Makefile                        # Команды автоматизации
├── .gitignore                      # Что не коммитить
├── CONTRIBUTING.md                 # Этот файл
└── README.md
```

**Важно:** директории `backend/gen/`, `frontend/src/gen/`, `node_modules/` и `.venv/` **не коммитятся** в git. Они перечислены в `.gitignore` и восстанавливаются командами выше.

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

- [ ] Я изменил(а) только исходный код (не `backend/gen/`, не `frontend/src/gen/`)
- [ ] Я изменил(а) `proto`-файл, если менял(а) API
- [ ] `make lint` проходит без ошибок
- [ ] `make generate` работает без ошибок
- [ ] Мой код работает локально

---

## 💬 Вопросы?

Если что-то не работает или непонятно — пишите в чат команды. Мы поможем!
