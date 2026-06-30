.PHONY: start install clean

.venv:
	python3 -m venv .venv

install: .venv
	.venv/bin/pip install -q -r requirements.txt

start: install
	@echo "  Starting GL SDK Backlog Manager on http://localhost:5050"
	@.venv/bin/python app.py

clean:
	rm -rf .venv
	rm -f authors.json
