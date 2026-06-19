PYTHON ?= python3

.PHONY: install test run

install:
	$(PYTHON) -m pip install -e '.[test]'

test:
	$(PYTHON) -m unittest discover -s tests -v

run:
	uvicorn service_monitor.app:app --host 127.0.0.1 --port 8090
