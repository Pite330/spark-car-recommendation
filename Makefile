PYTHON ?= python3

.PHONY: setup data spark run test

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install -r requirements.txt

data:
	.venv/bin/python scripts/fetch_public_dataset.py

spark:
	.venv/bin/python -m src.spark_jobs.clean_cars

run:
	.venv/bin/python -m src.web.app

test:
	.venv/bin/python -m pytest
