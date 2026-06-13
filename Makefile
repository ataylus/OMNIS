# OMNIS developer targets. Everything runs offline, no API keys.
PYTHON ?= python3

.PHONY: test eval run score report serve demo synth perf analyze

test:
	$(PYTHON) -m pytest

eval:
	$(PYTHON) -m omnis eval

run:
	$(PYTHON) -m omnis run

score:
	$(PYTHON) -m omnis score

report:
	$(PYTHON) -m omnis report --bench sample

serve:
	$(PYTHON) -m omnis serve --port 8000

# demo is the documented launch command; it is an alias for serve.
demo:
	$(PYTHON) -m omnis serve --port 8000

synth:
	$(PYTHON) -m omnis synth --out data/synthetic

perf:
	$(PYTHON) -m omnis perf --n 5000

analyze:
	$(PYTHON) scripts/label_signal_analysis.py
