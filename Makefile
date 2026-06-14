# OMNIS developer targets. Everything runs offline, no API keys required.
PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help test eval run score report serve demo synth perf analyze all clean

help: ## Show this help
	@printf "\n  \033[1mOMNIS\033[0m  the partly omniscient auditor\n"
	@printf "  \033[2mcompliance evidence engine  .  make <target>\033[0m\n\n"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*## "}; {printf "  \033[1m%-9s\033[0m %s\n", $$1, $$2}'
	@printf "\n"

test: ## Run the full test suite (97 tests)
	$(PYTHON) -m pytest

eval: ## Score the detector vs ground truth (precision/recall/F1)
	$(PYTHON) -m omnis eval

run: ## Parse policies + audit the provided sample corpus
	$(PYTHON) -m omnis run

score: ## Map evidence + compliance scoring on both benches
	$(PYTHON) -m omnis score

report: ## Write the auditor-ready JSON + PDF report (synthetic bench)
	$(PYTHON) -m omnis report --bench synthetic

serve: ## Serve the dashboard at http://127.0.0.1:8000
	$(PYTHON) -m omnis serve --port 8000

demo: ## Launch the dashboard (alias for serve)
	$(PYTHON) -m omnis serve --port 8000

synth: ## Regenerate the synthetic bench into data/synthetic
	$(PYTHON) -m omnis synth --out data/synthetic

collect: ## Run the mock evidence collectors (CloudTrail + config snapshot)
	$(PYTHON) -m omnis collect

perf: ## Time the full pipeline on 5,000 evidence rows
	$(PYTHON) -m omnis perf --n 5000

analyze: ## Reproduce the label-independence finding
	$(PYTHON) scripts/label_signal_analysis.py

all: ## Regenerate every artifact (eval, score, report, perf)
	$(PYTHON) -m omnis eval
	$(PYTHON) -m omnis score
	$(PYTHON) -m omnis report --bench synthetic
	$(PYTHON) -m omnis perf --n 5000

clean: ## Remove generated JSON outputs and Python caches (keeps report.pdf)
	rm -f reports/report.json reports/eval_latest.json reports/score_latest.json
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
