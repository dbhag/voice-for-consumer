.PHONY: setup api worker run test test-prompts test-integration dashboard lint

setup:
	uv venv && uv pip install -e ".[dev]"

api:
	uvicorn app.main:app --reload

worker:
	python -m app.agent.worker

run:
	python -m app.cli run --vertical rental --targets examples/rental_targets.json

test:
	pytest

test-prompts:
	pytest tests/prompts -v

test-integration:
	pytest -m integration

dashboard:
	cd dashboard && npm run dev

lint:
	mypy app/ engine/ verticals/ && ruff check app/ engine/ verticals/
