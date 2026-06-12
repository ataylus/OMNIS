# OMNIS developer targets. Everything runs offline, no API keys.
PYTHON ?= python3

.PHONY: test eval run

test:
	$(PYTHON) -m pytest

eval:
	$(PYTHON) -m omnis eval

run:
	$(PYTHON) -m omnis run
