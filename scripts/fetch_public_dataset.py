"""抓取公开展示的中国市场车型卡片，保存为可追溯的原始快照。

原始快照保留美元起售价，不在抓取阶段转换或补齐字段。网络抓取只用于
更新数据；仓库内已有快照时，Spark 和 Web 均可完全离线运行。
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "https://chinacarprices.com/models"
DEFAULT_OUTPUT = Path("data/raw/china_car_prices_snapshot.csv")
FIELDNAMES = [
    "source_slug",
    "brand",
    "model_name",
    "powertrain",
    "price_usd",
    "body_style",
    "model_year",
    "range_km",
    "horsepower",
    "seats",
    "source_url",
    "captured_at",
]


def _integer(text: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def parse_cards(html: str, captured_at: str) -> list[dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()

    for card in soup.select('a[href^="/models/"]'):
        href = card.get("href", "")
        if href in seen:
            continue
        parts = [part.strip() for part in card.get_text("|", strip=True).split("|")]
        if len(parts) < 13 or parts[3] != "From":
            continue

        seen.add(href)
        rows.append(
            {
                "source_slug": href.rsplit("/", 1)[-1],
                "powertrain": parts[0],
                "brand": parts[1],
                "model_name": parts[2],
                "price_usd": _integer(parts[4]),
                "body_style": parts[5],
                "model_year": _integer(parts[6]),
                "range_km": _integer(parts[7]),
                "horsepower": _integer(parts[9]),
                "seats": _integer(parts[11]),
                "source_url": f"https://chinacarprices.com{href}",
                "captured_at": captured_at,
            }
        )

    if len(rows) < 20:
        raise RuntimeError(f"仅解析到 {len(rows)} 条车型，拒绝覆盖现有快照")
    return rows


def fetch_html() -> str:
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "spark-car-recommendation-course-project/0.1"},
    )
    response.raise_for_status()
    return response.text


def main() -> None:
    parser = argparse.ArgumentParser(description="更新公开车型原始快照")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--captured-at", default=date.today().isoformat())
    args = parser.parse_args()

    rows = parse_cards(fetch_html(), args.captured_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已保存 {len(rows)} 条原始车型记录到 {args.output}")


if __name__ == "__main__":
    main()
