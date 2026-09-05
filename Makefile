.PHONY: help install venv lint generate clean format proto-all up down dev ps logs test smoke db-up db-down db-reset migrate migration

PROTO_FILES := $(shell find proto -name "*.proto")

help: ## Показать справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Установить все зависимости (однократно)
	@echo "📦 Создание виртуального окружения..."
	@test -d .venv || python3 -m venv .venv
	@echo "🐍 Установка Python зависимостей..."
	@.venv/bin/pip install grpcio-tools protobuf > /dev/null
	@echo "📦 Установка JS плагинов..."
	@cd frontend && npm install --save-dev @bufbuild/protoc-gen-es @connectrpc/protoc-gen-connect-es > /dev/null 2>&1
	@echo "✅ Все зависимости установлены"

lint: ## Проверить proto файлы
	@buf lint
	@echo "✅ Proto файлы в порядке"

generate: ## Сгенерировать Python + TypeScript код
	@test -d .venv || $(MAKE) --no-print-directory venv
	@echo "⚡ Генерация Python кода..."
	@.venv/bin/python -m grpc_tools.protoc -Iproto --python_out=backend/gen --grpc_python_out=backend/gen $(PROTO_FILES)
	@echo "⚡ Генерация TypeScript кода (в контейнере — protoc/node на хосте не нужны)..."
	@docker run --rm \
		-v "$(PWD)":/w \
		-v "$(shell .venv/bin/python -c 'import grpc_tools, os; print(os.path.join(os.path.dirname(grpc_tools.__file__), "_proto"))')":/wkt:ro \
		-w /w node:20-alpine sh -c '\
			apk add --no-cache protobuf >/dev/null 2>&1; \
			protoc \
				--plugin=protoc-gen-es=frontend/node_modules/.bin/protoc-gen-es \
				--plugin=protoc-gen-connect-es=frontend/node_modules/.bin/protoc-gen-connect-es \
				--es_out=frontend/src/gen --es_opt=target=ts \
				--connect-es_out=frontend/src/gen --connect-es_opt=target=ts \
				-I/wkt -Iproto $(PROTO_FILES)'
	@echo ""
	@echo "📁 Python файлы:"
	@find backend/gen -type f -name '*.py' 2>/dev/null || true
	@echo ""
	@echo "📁 TypeScript файлы:"
	@find frontend/src/gen -type f -name '*.ts' 2>/dev/null || true
	@echo ""
	@echo "⚠️  Сгенерированное коммитится вместе с .proto — иначе образ не соберётся."

venv: ## Создать .venv с grpcio-tools (нужен для генерации)
	@python3 -m venv .venv
	@.venv/bin/pip install -q --upgrade pip
	@.venv/bin/pip install -q grpcio-tools protobuf
	@echo "✅ .venv готов"

format: ## Отформатировать proto файлы
	@buf format -w
	@echo "✅ Отформатировано"

clean: ## Очистить сгенерированные файлы
	@rm -rf backend/gen/*
	@rm -rf frontend/src/gen/*
	@echo "🧹 Очищено"

proto-all: lint generate ## Проверить и сгенерировать

# =====================================================
# Запуск приложения
# =====================================================

up: ## Поднять весь стек (первая сборка фронта ~5-8 мин)
	@test -f .env || cp .env.example .env
	@docker compose up -d --build
	@echo "✅ UI: http://localhost   API: http://localhost/api/health"

dev: ## Стек без фронта — быстрее для работы над бэкендом
	@test -f .env || cp .env.example .env
	@docker compose up -d --build postgres redis backend worker
	@echo "✅ API: http://localhost:8000/api/health"

down: ## Остановить стек (данные Postgres сохраняются)
	@docker compose down

ps: ## Что запущено
	@docker compose ps

logs: ## Логи сервиса (по умолчанию worker; make logs s=backend)
	@docker compose logs -f $(or $(s),worker)

# =====================================================
# База данных
# =====================================================

db-up: ## Поднять только Postgres и Redis
	@docker compose up -d postgres redis
	@echo "✅ Postgres localhost:5432, Redis localhost:6379"

db-down: ## Остановить стек
	@docker compose down

db-reset: ## Полностью очистить БД (включая данные!)
	@docker compose down -v
	@echo "🗑  БД и все данные удалены"

test: ## Юнит-тесты бэкенда (без Postgres/Redis/сети — гоняются локально в образе)
	@docker compose build backend >/dev/null
	@docker compose run --rm --no-deps -e PYTHONPATH=/app:/app/gen backend sh -c "pip install -q -r requirements-dev.txt && pytest -q"

smoke: ## Сквозная проверка стека: CreateProject -> StartRun -> polling -> итог
	@python3 scripts/smoke.py

migrate: ## Применить миграции (внутри контейнера backend)
	@docker compose exec backend alembic upgrade head
	@echo "✅ Миграции применены"

migration: ## Создать миграцию (использование: make migration name="add users")
	@docker compose exec backend alembic revision --autogenerate -m "$(name)"
	@echo "✅ Миграция создана"
