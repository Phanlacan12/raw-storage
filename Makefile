SHELL = /bin/bash

CONDA_ENV = rawstorage
MAIN_FOLDER = src
TEST_FOLDER = tests
PY_FILES = $(shell find $(MAIN_FOLDER) -name "*.py")

.PHONY: venv style typecheck unit test run reconcile docs-check compose-up compose-down

# Môi trường: conda cấp interpreter 3.12, uv quản lý dependency.
# Chạy `conda activate rawstorage` trước khi dùng các target khác.
venv:
	conda create -n $(CONDA_ENV) python=3.12 -y || true
	$$CONDA_PREFIX/bin/python -m pip install uv
	uv venv --python "$$CONDA_PREFIX/bin/python"
	uv sync --all-extras --dev
	uv run pre-commit install

style:
	uv run pylint $(PY_FILES)

typecheck:
	uv run mypy src

unit:
	uv run pytest -s --durations=0 --disable-warnings $(TEST_FOLDER)/

# Thứ tự giống repo mẫu: mypy -> pytest -> pylint
test:
	set -euo pipefail; \
	uv run mypy src; \
	uv run pytest -s --durations=0 --disable-warnings $(TEST_FOLDER)/; \
	uv run pylint $(PY_FILES)

run:
	uv run uvicorn document_service.main:app --reload --port 8080

reconcile:
	uv run python -m document_service.worker.reconcile

docs-check:
	node docs/tools/check-mermaid.mjs docs

compose-up:
	docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

compose-down:
	docker compose -f deploy/docker-compose.yml down -v
