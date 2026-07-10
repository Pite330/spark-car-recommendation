PYTHON ?= python3
PDF_TARGETS := $(wildcard docs/*.pdf)

.PHONY: setup data spark pdf run test

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install -r requirements.txt

data:
	.venv/bin/python scripts/fetch_16888_dataset.py

spark:
	.venv/bin/python -m src.spark_jobs.clean_cars

pdf: $(PDF_TARGETS)

docs/%.pdf: docs/%.md scripts/markdown_to_pdf.py
	.venv/bin/python scripts/markdown_to_pdf.py $< $@

run:
	.venv/bin/python -m src.web.app

test:
	.venv/bin/python -m pytest
