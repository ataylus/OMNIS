# OMNIS developer targets. Everything runs offline, no API keys.
PYTHON ?= python3

.PHONY: test eval run score synth analyze

test:
	$(PYTHON) -m pytest

eval:
	$(PYTHON) -m omnis eval

run:
	$(PYTHON) -m omnis run

score:
	$(PYTHON) -m omnis score

synth:
	$(PYTHON) -m omnis synth --out data/synthetic

analyze:
	$(PYTHON) scripts/label_signal_analysis.py
