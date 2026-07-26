.PHONY: setup db-setup api worker run test test-prompts test-integration dashboard lint dev

dev:
	./dev.sh

setup:
	uv venv && uv pip install -e ".[dev]"

db-setup:
	./scripts/db_setup.sh

api:
	uvicorn app.main:app --reload

worker:
	python -m app.agent.worker

run:
	python -m app.cli run --vertical rental --targets examples/rental_targets.json

test:
	pytest

test-prompts:
	pytest tests/prompts -v -m integration

test-integration:
	pytest -m integration

dashboard:
	cd dashboard && npm run dev

lint:
	mypy app/ engine/ && ruff check app/ engine/
