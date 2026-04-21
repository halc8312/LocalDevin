.PHONY: setup run ask review index test lint status

setup:
	pip install -e .
	docker compose up -d
	ollama pull qwen3.6:35b-a3b-q4_K_M
	ollama pull qwen3.5:9b
	@echo "Setup complete. Run 'make run TASK=\"your task\" REPO=.' to start."

run:
	localdevin run "$(TASK)" --repo $(REPO)

ask:
	localdevin ask "$(Q)" --repo $(REPO)

review:
	localdevin review --repo $(REPO)

index:
	localdevin index --repo $(REPO)

status:
	localdevin status

test:
	pytest tests/ -v

lint:
	ruff check .
	mypy .

docker-up:
	docker compose up -d

docker-down:
	docker compose down
