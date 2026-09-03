.PHONY: help install lint generate clean format proto-all

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
	@echo "⚡ Генерация Python кода..."
	@.venv/bin/python -m grpc_tools.protoc -Iproto --python_out=backend/gen --grpc_python_out=backend/gen $(PROTO_FILES)
	@echo "⚡ Генерация TypeScript кода..."
	@protoc --plugin=protoc-gen-es=frontend/node_modules/.bin/protoc-gen-es --plugin=protoc-gen-connect-es=frontend/node_modules/.bin/protoc-gen-connect-es --es_out=frontend/src/gen --es_opt=target=ts --connect-es_out=frontend/src/gen --connect-es_opt=target=ts -Iproto $(PROTO_FILES)
	@echo ""
	@echo "📁 Python файлы:"
	@find backend/gen -type f -name '*.py' 2>/dev/null || true
	@echo ""
	@echo "📁 TypeScript файлы:"
	@find frontend/src/gen -type f -name '*.ts' 2>/dev/null || true

format: ## Отформатировать proto файлы
	@buf format -w
	@echo "✅ Отформатировано"

clean: ## Очистить сгенерированные файлы
	@rm -rf backend/gen/*
	@rm -rf frontend/src/gen/*
	@echo "🧹 Очищено"

proto-all: lint generate ## Проверить и сгенерировать