PYTHON ?= python3
PDF_TARGETS := $(wildcard docs/*.pdf)

.PHONY: setup data-full-pilot data-full spark analyze pdf run test

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install -r requirements.txt

data-full-pilot:
	.venv/bin/python scripts/fetch_16888_full_options.py --max-series 20

data-full:
	.venv/bin/python scripts/fetch_16888_full_options.py

spark:
	.venv/bin/python -m src.spark_jobs.clean_cars

analyze:
	.venv/bin/python -m src.spark_jobs.analyze_parameter_sales

pdf: $(PDF_TARGETS)

docs/%.pdf: docs/%.md scripts/markdown_to_pdf.py
	.venv/bin/python scripts/markdown_to_pdf.py $< $@

run:
	.venv/bin/python -m src.web.app

test:
	.venv/bin/python -m pytest
