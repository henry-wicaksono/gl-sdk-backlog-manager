.PHONY: install start clean

install:
	uv sync

start:
	@echo "  Starting GL SDK Backlog Manager on http://localhost:5050"
	@uv run python app.py

clean:
	rm -rf .venv
	rm -f authors.json
