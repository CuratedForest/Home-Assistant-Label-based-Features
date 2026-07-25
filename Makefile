PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF   ?= .venv/bin/ruff

.PHONY: venv install lint test hassfest ci clean

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install pytest-homeassistant-custom-component ruff

lint:
	$(RUFF) check custom_components/labeled_features tests

lint-fix:
	$(RUFF) check --fix custom_components/labeled_features tests

test:
	$(PYTEST) tests

hassfest:
	# Requires the HA core repo. Skips gracefully when unavailable so
	# local dev without a checkout still works.
	@if [ -d "$${HA_CORE:-}" ]; then \
	  $(PYTHON) -m script.hassfest --integration-path custom_components/labeled_features; \
	else \
	  echo "hassfest: set HA_CORE to your homeassistant/core checkout to run manifest validation"; \
	fi

ci: lint test

clean:
	rm -rf .venv .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
