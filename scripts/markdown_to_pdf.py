"""将 UTF-8 Markdown 转换为适合课程提交的 A4 PDF。

Markdown 是唯一可编辑源文件；PDF 仅作为同名派生产物。支持标题、段落、
有序/无序列表、引用、代码块、表格，以及 ``<!-- pagebreak -->`` 分页标记。
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


FONT_CANDIDATES = [
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
]
FONT = "MarkdownCJK"
NAVY = colors.HexColor("#173651")
BLUE = colors.HexColor("#1769c2")
TEXT = colors.HexColor("#24364a")
GRID = colors.HexColor("#c8d7e5")


def register_font() -> None:
    path = next((item for item in FONT_CANDIDATES if item.exists()), None)
    if path is None:
        raise FileNotFoundError("未找到 Arial Unicode 字体，无法可靠生成中文 PDF")
    pdfmetrics.registerFont(TTFont(FONT, str(path)))


def paragraph_style(name: str, **options) -> ParagraphStyle:
    settings = {"fontName": FONT, "textColor": TEXT, "wordWrap": "CJK"}
    settings.update(options)
    return ParagraphStyle(name, **settings)


def inline_markdown(value: str) -> str:
    value = html.escape(value.strip())
    value = re.sub(r"`([^`]+)`", rf'<font name="{FONT}" color="#1769c2">\1</font>', value)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)


def column_widths(count: int, available: float) -> list[float]:
    ratios = {
        2: [0.29, 0.71],
        3: [0.24, 0.48, 0.28],
        4: [0.13, 0.23, 0.52, 0.12],
        5: [0.15, 0.43, 0.13, 0.14, 0.15],
    }.get(count, [1 / count] * count)
    return [available * ratio for ratio in ratios]


def markdown_table(rows: list[list[str]], available: float, body, head) -> Table:
    columns = max(len(row) for row in rows)
    padded = [row + [""] * (columns - len(row)) for row in rows]
    data = [
        [Paragraph(inline_markdown(cell), head if index == 0 else body) for cell in row]
        for index, row in enumerate(padded)
    ]
    table = Table(data, colWidths=column_widths(columns, available), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fb")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def parse_markdown(source: str, available: float):
    title = paragraph_style("title", fontSize=22, leading=28, spaceAfter=22, textColor=NAVY)
    heading = paragraph_style(
        "heading", fontSize=15, leading=21, spaceBefore=12, spaceAfter=8, textColor=NAVY, keepWithNext=True
    )
    subheading = paragraph_style(
        "subheading", fontSize=12, leading=18, spaceBefore=7, spaceAfter=5, textColor=BLUE, keepWithNext=True
    )
    body = paragraph_style("body", fontSize=10.2, leading=16, spaceAfter=7)
    listed = paragraph_style("list", fontSize=10.2, leading=16, leftIndent=16, firstLineIndent=-10, spaceAfter=4)
    code = paragraph_style("code", fontSize=8.7, leading=13)
    table_body = paragraph_style("table", fontSize=8.5, leading=12)
    table_head = paragraph_style("table-head", fontSize=8.6, leading=12, textColor=colors.white, alignment=TA_CENTER)

    lines = source.splitlines()
    story, paragraph = [], []
    index = 0

    def flush() -> None:
        if paragraph:
            story.append(Paragraph(inline_markdown(" ".join(paragraph)), body))
            paragraph.clear()

    while index < len(lines):
        line = lines[index].rstrip()
        if not line.strip():
            flush()
        elif line.strip() == "<!-- pagebreak -->":
            flush()
            story.append(PageBreak())
        elif line.startswith("```"):
            flush()
            block = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(html.escape(lines[index]))
                index += 1
            box = Table([[Paragraph("<br/>".join(block), code)]], colWidths=[available])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f4f7")), ("BOX", (0, 0), (-1, -1), 0.4, GRID), ("PADDING", (0, 0), (-1, -1), 8)]))
            story.extend([box, Spacer(1, 5)])
        elif line.startswith("|") and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[index + 1]):
            flush()
            rows = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", cell.replace(" ", "")) for cell in cells):
                    rows.append(cells)
                index += 1
            story.extend([markdown_table(rows, available, table_body, table_head), Spacer(1, 8)])
            continue
        elif line.startswith("# "):
            flush()
            story.append(Paragraph(inline_markdown(line[2:]), title))
        elif line.startswith("## "):
            flush()
            story.append(Paragraph(inline_markdown(line[3:]), heading))
        elif line.startswith("### "):
            flush()
            story.append(Paragraph(inline_markdown(line[4:]), subheading))
        elif line.startswith("> "):
            flush()
            box = Table([[Paragraph(inline_markdown(line[2:]), body)]], colWidths=[available])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf4fa")), ("PADDING", (0, 0), (-1, -1), 9)]))
            story.extend([box, Spacer(1, 6)])
        elif match := re.match(r"^(\d+)\.\s+(.*)", line):
            flush()
            story.append(Paragraph(f'<font color="#1769c2">{match.group(1)}</font>　{inline_markdown(match.group(2))}', listed))
        elif line.startswith("- "):
            flush()
            story.append(Paragraph(f'<font color="#1769c2">•</font>　{inline_markdown(line[2:])}', listed))
        else:
            paragraph.append(line.strip())
        index += 1
    flush()
    return story


def convert(input_path: Path, output_path: Path, author: str) -> None:
    register_font()
    source = input_path.read_text(encoding="utf-8")
    document_title = next((line[2:].strip() for line in source.splitlines() if line.startswith("# ")), input_path.stem)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=19 * mm, bottomMargin=20 * mm, title=document_title, author=author,
    )

    def footer(canvas, current) -> None:
        canvas.saveState()
        canvas.setStrokeColor(GRID)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(colors.HexColor("#60778e"))
        canvas.drawString(18 * mm, 9.5 * mm, document_title.split("——", 1)[0][:28])
        canvas.drawRightString(A4[0] - 18 * mm, 9.5 * mm, f"第 {current.page} 页")
        canvas.restoreState()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(parse_markdown(source, doc.width), onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    parser = argparse.ArgumentParser(description="将 Markdown 转换为 A4 中文 PDF")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--author", default="华迪企业生产实习项目组")
    args = parser.parse_args()
    convert(args.input, args.output or args.input.with_suffix(".pdf"), args.author)


if __name__ == "__main__":
    main()
