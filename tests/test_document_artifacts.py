from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_pdf_has_a_same_named_markdown_source():
    pdfs = list((ROOT / "docs").rglob("*.pdf"))
    assert pdfs
    for pdf in pdfs:
        assert pdf.with_suffix(".md").is_file(), f"{pdf} 缺少同名 Markdown 源文件"
        assert pdf.read_bytes().startswith(b"%PDF-")
