SHELL = /bin/bash

CONDA_ENV = rawstorage
MAIN_FOLDER = src
TEST_FOLDER = tests
PY_FILES = $(shell find $(MAIN_FOLDER) -name "*.py")

.PHONY: venv requirements format style lint typecheck unit test examples run reconcile docs-check compose-up compose-down

# Môi trường: conda cấp interpreter 3.12, uv quản lý dependency.
# Sau khi `make venv`, dùng một trong hai cách để vào môi trường:
#   source .venv/bin/activate     (uv + pip được cài sẵn trong .venv)
#   conda activate $(CONDA_ENV)   (dùng uv của conda env)
venv:
	conda create -n $(CONDA_ENV) python=3.12 -y || true
	$$CONDA_PREFIX/bin/python -m pip install uv
	uv venv --python "$$CONDA_PREFIX/bin/python"
	uv sync --all-extras --dev
	# pip: cho extension Python của VSCode liệt kê package.
	# uv:  để `source .venv/bin/activate` là đủ chạy mọi target, không cần conda.
	uv pip install pip uv
	uv run pre-commit install

# Đồng bộ requirements.txt từ [project.dependencies] trong pyproject.toml.
requirements:
	uv export --no-hashes --no-dev --no-emit-project --format requirements-txt \
		-o requirements.lock.txt
	@echo "Wrote requirements.lock.txt (fully pinned). requirements.txt keeps the soft constraints; edit it by hand when pyproject.toml changes."

# Tự động định dạng lại code (ghi đè file), giống target `style` của repo mẫu.
format:
	uv run isort $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py
	uv run black $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py

# Chỉ kiểm tra, không sửa: dùng cho CI và pre-commit.
style:
	uv run isort --check-only --diff $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py
	uv run black --check --diff $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py
	uv run flake8 $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py
	uv run pylint $(PY_FILES)

# flake8 chạy nhanh (pycodestyle + pyflakes), dùng để soát trước khi gọi pylint.
lint:
	uv run flake8 $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py

typecheck:
	uv run mypy src

unit:
	uv run pytest -s --durations=0 --disable-warnings $(TEST_FOLDER)/

# Thứ tự: isort/black (check) -> mypy -> pytest -> flake8 -> pylint
test:
	set -euo pipefail; \
	uv run isort --check-only $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py; \
	uv run black --check $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py; \
	uv run mypy src; \
	uv run pytest -s --durations=0 --disable-warnings $(TEST_FOLDER)/; \
	uv run flake8 $(MAIN_FOLDER) $(TEST_FOLDER) examples setup.py; \
	uv run pylint $(PY_FILES)

# Chạy mọi ví dụ không cần hạ tầng; dừng ở ví dụ đầu tiên thất bại
examples:
	uv run python examples/run_all.py

run:
	uv run uvicorn document_service.main:app --reload --port 8080

reconcile:
	uv run python -m document_service.worker.reconcile

docs-check:
	npm install --no-save --silent mermaid@11.12.0 jsdom@26.1.0
	node docs/tools/check-mermaid.mjs docs

compose-up:
	docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

compose-down:
	docker compose -f deploy/docker-compose.yml down -v
