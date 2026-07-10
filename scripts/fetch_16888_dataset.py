"""低频采集车主之家（16888.com）公开车型、参数与销量快照。

采集范围不是全站：按车身级别选取热门在售车系，再补充新能源分类中的
热门车系。每个车系最多请求一次公开参数接口和一次销量页面；请求串行、
带间隔和本地重试，不绕过登录、验证码或访问限制。
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


FORM_URL = "https://auto.16888.com/form.html"
EV_URL = "https://auto.16888.com/ev.html"
OPTIONS_API = "https://www.16888.com/auto/auto.php?mod=auto&extra=scapi"
DEFAULT_OUTPUT = Path("data/raw/16888_cars_snapshot.csv")

BODY_LIMITS = {
    "微型车": 10,
    "小型车": 10,
    "紧凑型车": 12,
    "中型车": 12,
    "中大型车": 10,
    "MPV": 12,
    "SUV": 20,
    "大型车": 6,
}
ENERGY_LIMITS = {
    "纯电动车": 35,
    "插电式混合电动车": 20,
    "非插电式混合电动车": 15,
    "增程式电动车": 20,
}
FIELDNAMES = [
    "source_key",
    "series_id",
    "model_name",
    "brand",
    "price_min_wan",
    "price_max_wan",
    "level_name",
    "body_structure",
    "energy_type",
    "seats",
    "range_km",
    "fuel_consumption",
    "horsepower",
    "model_year",
    "sales",
    "sales_period",
    "trim_count",
    "source_url",
    "options_url",
    "sales_url",
    "captured_at",
]


@dataclass
class SeriesCandidate:
    series_id: str
    name: str
    list_price_min: float | None
    list_price_max: float | None
    body_hints: set[str] = field(default_factory=set)
    energy_hints: set[str] = field(default_factory=set)

    @property
    def source_url(self) -> str:
        return f"https://www.16888.com/{self.series_id}/"

    @property
    def options_url(self) -> str:
        return f"https://www.16888.com/{self.series_id}/options/"

    @property
    def sales_url(self) -> str:
        return f"https://xl.16888.com/s/{self.series_id}/"


class PoliteClient:
    def __init__(self, delay: float) -> None:
        self.delay = max(delay, 0)
        self.last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "spark-car-recommendation-course-project/0.2 (+educational snapshot)"}
        )

    def get(self, url: str, *, referer: str | None = None, params: dict[str, Any] | None = None):
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        headers = {"Referer": referer} if referer else None
        error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=25, allow_redirects=True
                )
                self.last_request_at = time.monotonic()
                response.raise_for_status()
                response.encoding = response.apparent_encoding or "utf-8"
                return response
            except requests.RequestException as exc:
                error = exc
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
        assert error is not None
        raise error


def parse_price_range(text: str) -> tuple[float | None, float | None]:
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
    if not values:
        return None, None
    return min(values), max(values)


def parse_number(value: object) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def mode(values: list[object]) -> str | None:
    cleaned = [str(value).strip() for value in values if str(value or "").strip() not in {"", "-"}]
    return Counter(cleaned).most_common(1)[0][0] if cleaned else None


def normalize_energy(value: str) -> str | None:
    text = value.strip()
    if "纯电" in text:
        return "纯电"
    if "插电" in text:
        return "插混"
    if "增程" in text:
        return "增程"
    if "混合" in text or "轻混" in text:
        return "混动"
    if any(name in text for name in ["汽油", "柴油", "天然气"]):
        return "燃油"
    return None


def series_from_page(
    html: str,
    limits: dict[str, int],
    *,
    hint_type: str,
) -> list[SeriesCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    result: list[SeriesCandidate] = []
    for title in soup.select("div.brand_title"):
        category = title.get_text(" ", strip=True)
        if category not in limits:
            continue
        box = title.find_next_sibling("div", class_="brand_box")
        if box is None:
            continue
        accepted = 0
        for item in box.select("li"):
            series_link = next(
                (
                    link
                    for link in item.select("a[href]")
                    if re.fullmatch(r"https://www\.16888\.com/\d+/", link.get("href", ""))
                    and link.get_text(" ", strip=True)
                ),
                None,
            )
            if series_link is None:
                continue
            series_id = series_link["href"].rstrip("/").rsplit("/", 1)[-1]
            price_link = next(
                (link for link in item.select("a[href]") if "price.16888.com/sr-" in link.get("href", "")),
                None,
            )
            price_min, price_max = parse_price_range(
                price_link.get_text(" ", strip=True) if price_link else ""
            )
            if price_min is None:
                continue
            candidate = SeriesCandidate(
                series_id=series_id,
                name=series_link.get_text(" ", strip=True),
                list_price_min=price_min,
                list_price_max=price_max,
            )
            if hint_type == "body":
                candidate.body_hints.add(category)
            else:
                candidate.energy_hints.add(category)
            result.append(candidate)
            accepted += 1
            if accepted >= limits[category]:
                break
    return result


def merge_candidates(*groups: list[SeriesCandidate]) -> list[SeriesCandidate]:
    merged: OrderedDict[str, SeriesCandidate] = OrderedDict()
    for group in groups:
        for candidate in group:
            current = merged.get(candidate.series_id)
            if current is None:
                merged[candidate.series_id] = candidate
            else:
                current.body_hints.update(candidate.body_hints)
                current.energy_hints.update(candidate.energy_hints)
    return list(merged.values())


def config_field(config: dict[str, object], field_name: str) -> list[object]:
    for group in config.values():
        if not isinstance(group, dict):
            continue
        for fields in group.values():
            if isinstance(fields, dict) and field_name in fields:
                values = fields[field_name]
                return list(values) if isinstance(values, list) else []
    return []


def latest_sales(client: PoliteClient, candidate: SeriesCandidate) -> tuple[int | None, str | None]:
    response = client.get(candidate.sales_url, referer=candidate.source_url)
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.select_one("table")
    if table is None:
        return None, None
    for row in table.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
        if len(cells) >= 2 and re.fullmatch(r"20\d{2}-\d{2}", cells[0]):
            sales = parse_number(cells[1])
            return (int(sales) if sales is not None else None), cells[0]
    return None, None


def aggregate_options(
    client: PoliteClient,
    candidate: SeriesCandidate,
    captured_at: str,
    sales: int | None,
    sales_period: str | None,
) -> list[dict[str, object]]:
    payload = client.get(
        OPTIONS_API,
        referer=candidate.options_url,
        params={"sid": candidate.series_id, "decade": 0},
    ).json()
    data = payload.get("data", {}) if payload.get("ret") == "ok" else {}
    cars = data.get("arrCar", []) if isinstance(data, dict) else []
    config = data.get("arrConfig", {}) if isinstance(data, dict) else {}
    if not isinstance(cars, list) or not isinstance(config, dict) or not cars:
        return []

    prices = config_field(config, "厂商指导价(元)")
    brands = config_field(config, "厂商")
    levels = config_field(config, "级别")
    horsepower = config_field(config, "最大马力(Ps)")
    fuel_consumption = config_field(config, "工信部综合油耗(L)")

    grouped: dict[str, list[dict[str, object]]] = {}
    for index, car in enumerate(cars):
        if not isinstance(car, dict):
            continue
        energy = normalize_energy(str(car.get("fueltype") or ""))
        price = parse_number(prices[index] if index < len(prices) else None)
        if energy is None or price is None:
            continue
        grouped.setdefault(energy, []).append(
            {
                "price": price,
                "brand": brands[index] if index < len(brands) else None,
                "level": levels[index] if index < len(levels) else None,
                "body_structure": car.get("body_structure"),
                "seats": parse_number(car.get("seatnum")),
                "horsepower": parse_number(horsepower[index] if index < len(horsepower) else None),
                "fuel_consumption": parse_number(
                    fuel_consumption[index] if index < len(fuel_consumption) else None
                ),
                "model_year": parse_number(car.get("decade")),
            }
        )

    rows: list[dict[str, object]] = []
    for energy, trims in grouped.items():
        price_values = [float(trim["price"]) for trim in trims]
        brand = mode([trim["brand"] for trim in trims])
        level = mode([trim["level"] for trim in trims]) or mode(list(candidate.body_hints))
        structure = mode([trim["body_structure"] for trim in trims])
        seat_values = [int(trim["seats"]) for trim in trims if trim["seats"] is not None]
        hp_values = [int(trim["horsepower"]) for trim in trims if trim["horsepower"] is not None]
        fuel_values = [
            float(trim["fuel_consumption"])
            for trim in trims
            if trim["fuel_consumption"] is not None
        ]
        year_values = [int(trim["model_year"]) for trim in trims if trim["model_year"] is not None]
        if not brand or not level:
            continue
        model_name = candidate.name if len(grouped) == 1 else f"{candidate.name} {energy}版"
        rows.append(
            {
                "source_key": f"{candidate.series_id}_{energy}",
                "series_id": candidate.series_id,
                "model_name": model_name,
                "brand": brand,
                "price_min_wan": min(price_values),
                "price_max_wan": max(price_values),
                "level_name": level,
                "body_structure": structure or "",
                "energy_type": energy,
                "seats": Counter(seat_values).most_common(1)[0][0] if seat_values else "",
                "range_km": "",
                "fuel_consumption": round(sum(fuel_values) / len(fuel_values), 2)
                if fuel_values
                else "",
                "horsepower": max(hp_values) if hp_values else "",
                "model_year": max(year_values) if year_values else "",
                "sales": sales if sales is not None else "",
                "sales_period": sales_period or "",
                "trim_count": len(trims),
                "source_url": candidate.source_url,
                "options_url": candidate.options_url,
                "sales_url": candidate.sales_url,
                "captured_at": captured_at,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="更新 16888 公开车型快照")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--captured-at", default=date.today().isoformat())
    parser.add_argument("--delay", type=float, default=0.25, help="相邻请求最小间隔（秒）")
    parser.add_argument("--max-series", type=int, default=0, help="调试时限制车系数量")
    args = parser.parse_args()

    client = PoliteClient(args.delay)
    form_html = client.get(FORM_URL).text
    ev_html = client.get(EV_URL).text
    candidates = merge_candidates(
        series_from_page(form_html, BODY_LIMITS, hint_type="body"),
        series_from_page(ev_html, ENERGY_LIMITS, hint_type="energy"),
    )
    if args.max_series > 0:
        candidates = candidates[: args.max_series]

    rows: list[dict[str, object]] = []
    failures: list[str] = []
    for index, candidate in enumerate(candidates, 1):
        try:
            sales, period = latest_sales(client, candidate)
            rows.extend(
                aggregate_options(client, candidate, args.captured_at, sales, period)
            )
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            failures.append(f"{candidate.series_id}:{type(exc).__name__}")
        if index % 20 == 0 or index == len(candidates):
            print(f"进度 {index}/{len(candidates)}，已生成 {len(rows)} 行")

    minimum_rows = min(50, max(1, len(candidates) // 2))
    if len(rows) < minimum_rows:
        raise RuntimeError(f"仅生成 {len(rows)} 行，拒绝覆盖现有数据；失败：{failures[:10]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"已保存 {len(rows)} 行、{len(candidates)} 个车系到 {args.output}；"
        f"失败 {len(failures)} 个"
    )


if __name__ == "__main__":
    main()
