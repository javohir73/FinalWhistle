# Root task runner. "make test" runs BOTH test suites — the end-of-step gate.

.PHONY: test test-py test-js install

# Run every test suite (Python + frontend). This is the "test:all" gate.
test: test-py test-js

# Python tests (backend / ml / pipeline) via pytest in the project venv.
test-py:
	.venv/bin/python -m pytest

# Frontend tests (TypeScript) via Jest.
test-js:
	cd frontend && npm test

# One-time local setup.
install:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install
