.PHONY: setup up down logs migrate test lint frontend-test

setup:
	cp .env.example .env

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker frontend

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check app tests
	docker compose run --rm api mypy app

frontend-test:
	docker compose run --rm frontend npm run check

