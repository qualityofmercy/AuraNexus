.PHONY: install test lint fmt-tf validate-tf catalog demo run up

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

catalog:
	python scripts/gen_agent_catalog.py

demo:
	python scripts/demo.py

run:
	AURANEXUS_ENV=local uvicorn auranexus.api.app:create_app --factory --port 8080 --reload

up:
	docker compose up --build

fmt-tf:
	terraform fmt -recursive modules environments

validate-tf:
	for d in shared-services dev prod; do (cd environments/$$d && terraform init -backend=false -input=false && terraform validate); done
