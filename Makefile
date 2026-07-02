DFX_BIN := $(HOME)/Library/Application Support/org.dfinity.dfx/bin
export PATH := $(DFX_BIN):$(PATH)

VENV := venv
DEV_VENV := .venv-dev
PY310 := $(HOME)/.pyenv/versions/3.10.7/bin/python

.PHONY: setup sync test dev start stop deploy e2e determinism budgets clean

## setup: create both venvs (deploy: kybra+pyre, dev: +pytest) and dfx extension
setup:
	test -d $(VENV) || $(PY310) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet kybra==0.7.1
	$(VENV)/bin/pip install --quiet .
	$(VENV)/bin/python -m kybra install-dfx-extension
	test -d $(DEV_VENV) || $(PY310) -m venv $(DEV_VENV)
	$(DEV_VENV)/bin/pip install --quiet --upgrade pip
	$(DEV_VENV)/bin/pip install --quiet pytest -e .

## sync: reinstall pyre into the deploy venv (run after editing pyre/)
sync:
	$(VENV)/bin/pip install --quiet --force-reinstall --no-deps .

test:
	$(DEV_VENV)/bin/python -m pytest tests/unit -q

dev:
	$(DEV_VENV)/bin/pyre dev examples/rest_api/src/app.py

start:
	dfx start --background --clean

stop:
	dfx stop

## deploy: sync pyre then deploy all three canisters to the local replica
deploy: sync
	. $(VENV)/bin/activate && dfx deploy

e2e:
	bash scripts/e2e_local.sh

determinism:
	bash scripts/determinism_test.sh

budgets:
	bash scripts/measure_budgets.sh

## mainnet targets (need the pyre-dev identity funded — see DECISIONS.md)
mainnet-deploy: sync
	. $(VENV)/bin/activate && DFX_WARNING=-mainnet_plaintext_identity dfx deploy --network ic --identity pyre-dev

mainnet-gate:
	bash scripts/mainnet_gate.sh

mainnet-cost:
	bash scripts/mainnet_cost.sh

## budget-gate: fail if framework instruction costs regress (CI gate)
budget-gate:
	bash scripts/budget_gate.sh

## teardown-mainnet: withdraw cycles then delete (usage: make teardown-mainnet C="rest_api outbound")
teardown-mainnet:
	bash scripts/teardown_mainnet.sh $(C)

clean:
	rm -rf .dfx .kybra examples/*/.kybra
