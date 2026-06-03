.PHONY: install dev demo demo-good test clean

# Install the package (production)
PYTHON ?= python3

install:
	$(PYTHON) -m pip install .

# Install in editable mode for development
dev:
	$(PYTHON) -m pip install -e .

# Run against the bad example (triggers all 21 checks)
demo:
	terraform-cost-review ./examples/bad_infra --output-dir reports/

# Run against the good example (should score ~90%)
demo-good:
	terraform-cost-review ./examples/good_infra --output-dir reports/

# Smoke-test: verify all modules import and checks load correctly
test:
	@$(PYTHON) -c "from terraform_cost_reviewer.cli import main; print('cli OK')"
	@$(PYTHON) -c "from terraform_cost_reviewer import tools, report, rubric; print('modules OK')"
	@$(PYTHON) -c "from terraform_cost_reviewer.rubric import CHECKS; print(f'checks OK ({len(CHECKS)} loaded)')"
	@$(PYTHON) -c "from terraform_cost_reviewer.tools import run_cost_checks; r = run_cost_checks('./examples/bad_infra'); assert '0/21' in r, f'bad_infra should score 0/21, got: {[l for l in r.splitlines() if \"TOTAL\" in l]}'; print('bad_infra OK (0/21)')"
	@$(PYTHON) -c "from terraform_cost_reviewer.tools import run_cost_checks; r = run_cost_checks('./examples/good_infra'); ok = any(f'{n}/21' in r for n in range(18, 22)); assert ok, f'good_infra should score 18+/21, got: {[l for l in r.splitlines() if \"TOTAL\" in l]}'; print('good_infra OK')"
	@echo "All checks passed."

clean:
	rm -rf reports/ dist/ build/ *.egg-info __pycache__ terraform_cost_reviewer/__pycache__
