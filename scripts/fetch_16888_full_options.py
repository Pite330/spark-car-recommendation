"""低频采集 16888 在售车系的完整配置参数和月销量历史。

脚本先缓存每个车系的公开参数 JSON 和销量 HTML，再生成适合 Spark 清洗与
参数分析的规范化完整表。运行中断后可以直接重跑；已存在的原始响应默认不会
重复请求。
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests
from bs4 import BeautifulSoup

FORM_URL = "https://auto.16888.com/form.html"
EV_URL = "https://auto.16888.com/ev.html"
OPTIONS_API = "https://www.16888.com/auto/auto.php?mod=auto&extra=scapi"
DEFAULT_OUTPUT_DIR = Path("data/raw/16888_full")
ALL_BODY_LIMITS = {
    name: 100_000
    for name in ["微型车", "小型车", "紧凑型车", "中型车", "中大型车", "大型车", "跑车", "SUV", "MPV"]
}
ALL_ENERGY_LIMITS = {
    name: 100_000
    for name in ["纯电动车", "插电式混合电动车", "非插电式混合电动车", "增程式电动车"]
}


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


def series_from_page(
    page_html: str,
    limits: dict[str, int],
    *,
    hint_type: str,
) -> list[SeriesCandidate]:
    soup = BeautifulSoup(page_html, "html.parser")
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


SERIES_FIELDS = [
    "series_id",
    "series_name",
    "list_price_min_wan",
    "list_price_max_wan",
    "body_hints",
    "energy_hints",
    "source_url",
    "options_url",
    "sales_url",
    "captured_at",
]
TRIM_FIELDS = [
    "trim_id",
    "series_id",
    "trim_name",
    "model_year",
    "status",
    "energy_type_raw",
    "displacement",
    "transmission",
    "drive_style",
    "body_structure",
    "seats_raw",
    "options_url",
    "captured_at",
]
PARAMETER_FIELDS = [
    "parameter_key",
    "group_id",
    "group_name",
    "parameter_name",
    "declared_unit",
]
TRIM_PARAMETER_FIELDS = [
    "trim_id",
    "series_id",
    "parameter_key",
    "group_id",
    "group_name",
    "parameter_name",
    "value_raw",
    "value_text",
    "value_numeric",
    "value_unit",
    "equipment_state",
    "captured_at",
]
SALES_FIELDS = [
    "series_id",
    "sales_period",
    "sales",
    "overall_rank",
    "manufacturer_share",
    "manufacturer_rank",
    "segment_rank",
    "registration_related",
    "sales_url",
    "captured_at",
]


def clean_value(value: object) -> str:
    """将接口中的 HTML 实体和极少量标签转换为可分析文本。"""

    text = html.unescape(str(value or "")).replace("\xa0", " ")
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def split_parameter_unit(parameter_name: str) -> tuple[str, str]:
    match = re.search(r"\(([^()]*)\)\s*$", parameter_name)
    return (parameter_name[: match.start()].strip(), match.group(1).strip()) if match else (parameter_name, "")


def numeric_value(value_text: str) -> tuple[str, str]:
    """只解析完整的单一数值，避免把尺寸、前后轮胎等复合值误当成数值。"""

    match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)\s*(万|%|[A-Za-z]+(?:/[A-Za-z0-9]+)?|公里|小时|秒)?", value_text)
    if not match:
        return "", ""
    return match.group(1), match.group(2) or ""


def equipment_state(value_text: str) -> str:
    compact = value_text.replace(" ", "")
    if compact in {"", "-", "--"}:
        return "missing"
    has_standard = "●" in compact
    has_optional = "○" in compact
    if has_standard and has_optional:
        return "mixed"
    if has_standard:
        return "standard"
    if has_optional:
        return "optional"
    return "value"


def parameter_key(group_id: str, group_name: str, parameter_name: str) -> str:
    return "|".join([group_id, group_name, parameter_name])


def infer_series_name(candidate: SeriesCandidate, payload: dict[str, object] | None) -> str:
    if candidate.name != candidate.series_id or not payload:
        return candidate.name
    data = payload.get("data", {})
    cars = data.get("arrCar", []) if isinstance(data, dict) else []
    if not isinstance(cars, list) or not cars or not isinstance(cars[0], dict):
        return candidate.name
    trim_name = clean_value(cars[0].get("car_name"))
    inferred = re.split(r"\s+20\d{2}款(?:\s+|$)", trim_name, maxsplit=1)[0].strip()
    return inferred or candidate.name


def discover_candidates(client: PoliteClient) -> list[SeriesCandidate]:
    form_html = client.get(FORM_URL).text
    ev_html = client.get(EV_URL).text
    return merge_candidates(
        series_from_page(form_html, ALL_BODY_LIMITS, hint_type="body"),
        series_from_page(ev_html, ALL_ENERGY_LIMITS, hint_type="energy"),
    )


def manual_candidates(series_ids: Iterable[str]) -> list[SeriesCandidate]:
    result = []
    for series_id in series_ids:
        cleaned = series_id.strip()
        if not re.fullmatch(r"\d+", cleaned):
            raise ValueError(f"无效车系 ID：{series_id}")
        result.append(SeriesCandidate(cleaned, cleaned, None, None))
    return result


def candidate_record(candidate: SeriesCandidate) -> dict[str, object]:
    return {
        "series_id": candidate.series_id,
        "name": candidate.name,
        "list_price_min": candidate.list_price_min,
        "list_price_max": candidate.list_price_max,
        "body_hints": sorted(candidate.body_hints),
        "energy_hints": sorted(candidate.energy_hints),
    }


def load_selected_candidates(path: Path) -> list[SeriesCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("selected_series.json 不是数组")
    candidates: list[SeriesCandidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        series_id = str(item.get("series_id") or "").strip()
        if not re.fullmatch(r"\d+", series_id):
            continue
        candidates.append(
            SeriesCandidate(
                series_id=series_id,
                name=clean_value(item.get("name")) or series_id,
                list_price_min=item.get("list_price_min") if isinstance(item.get("list_price_min"), (int, float)) else None,
                list_price_max=item.get("list_price_max") if isinstance(item.get("list_price_max"), (int, float)) else None,
                body_hints=set(item.get("body_hints") or []),
                energy_hints=set(item.get("energy_hints") or []),
            )
        )
    return candidates


def cached_candidates(candidates: Iterable[SeriesCandidate], output_dir: Path) -> list[SeriesCandidate]:
    option_dir = output_dir / "responses" / "options"
    sales_dir = output_dir / "responses" / "sales"
    return [
        candidate
        for candidate in candidates
        if (option_dir / f"{candidate.series_id}.json").exists()
        or (sales_dir / f"{candidate.series_id}.html").exists()
    ]


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def fetch_raw_responses(
    client: PoliteClient,
    candidates: list[SeriesCandidate],
    output_dir: Path,
    *,
    force_refresh: bool,
) -> list[str]:
    failures: list[str] = []
    option_dir = output_dir / "responses" / "options"
    sales_dir = output_dir / "responses" / "sales"
    for index, candidate in enumerate(candidates, 1):
        option_path = option_dir / f"{candidate.series_id}.json"
        sales_path = sales_dir / f"{candidate.series_id}.html"
        if force_refresh or not option_path.exists():
            try:
                response = client.get(
                    OPTIONS_API,
                    referer=candidate.options_url,
                    params={"sid": candidate.series_id, "decade": 0},
                )
                payload = response.json()
                if payload.get("ret") != "ok":
                    raise ValueError(f"接口返回 {payload.get('ret')!r}")
                write_json_atomic(option_path, payload)
            except (requests.RequestException, ValueError, TypeError) as exc:
                failures.append(f"options:{candidate.series_id}:{type(exc).__name__}")
        if force_refresh or not sales_path.exists():
            try:
                response = client.get(candidate.sales_url, referer=candidate.source_url)
                write_text_atomic(sales_path, response.text)
            except requests.RequestException as exc:
                failures.append(f"sales:{candidate.series_id}:{type(exc).__name__}")
        if index % 20 == 0 or index == len(candidates):
            print(f"采集进度 {index}/{len(candidates)}，失败 {len(failures)}")
    return failures


def option_rows(
    candidate: SeriesCandidate,
    payload: dict[str, object],
    captured_at: str,
) -> tuple[list[dict[str, object]], Iterator[dict[str, object]], OrderedDict[str, dict[str, str]]]:
    data = payload.get("data", {}) if payload.get("ret") == "ok" else {}
    if not isinstance(data, dict):
        raise ValueError("参数接口缺少 data")
    cars = data.get("arrCar", [])
    config = data.get("arrConfig", {})
    if not isinstance(cars, list) or not isinstance(config, dict):
        raise ValueError("参数接口结构异常")

    trims: list[dict[str, object]] = []
    trim_ids: list[str] = []
    for car in cars:
        if not isinstance(car, dict):
            continue
        trim_id = str(car.get("car_id") or "").strip()
        if not trim_id:
            continue
        trim_ids.append(trim_id)
        trims.append(
            {
                "trim_id": trim_id,
                "series_id": candidate.series_id,
                "trim_name": clean_value(car.get("car_name")),
                "model_year": clean_value(car.get("decade")),
                "status": clean_value(car.get("status")),
                "energy_type_raw": clean_value(car.get("fueltype")),
                "displacement": clean_value(car.get("displacement")),
                "transmission": clean_value(car.get("transmission")),
                "drive_style": clean_value(car.get("driveStyle")),
                "body_structure": clean_value(car.get("body_structure")),
                "seats_raw": clean_value(car.get("seatnum")),
                "options_url": f"https://www.16888.com/c/{trim_id}/options/",
                "captured_at": captured_at,
            }
        )

    definitions: OrderedDict[str, dict[str, str]] = OrderedDict()

    def rows() -> Iterator[dict[str, object]]:
        for group_id, group in config.items():
            if not isinstance(group, dict):
                continue
            for group_name, fields in group.items():
                if not isinstance(fields, dict):
                    continue
                clean_group_name = clean_value(group_name)
                for raw_name, values in fields.items():
                    if not isinstance(values, list):
                        continue
                    clean_name = clean_value(raw_name)
                    _, declared_unit = split_parameter_unit(clean_name)
                    key = parameter_key(str(group_id), clean_group_name, clean_name)
                    definitions.setdefault(
                        key,
                        {
                            "parameter_key": key,
                            "group_id": str(group_id),
                            "group_name": clean_group_name,
                            "parameter_name": clean_name,
                            "declared_unit": declared_unit,
                        },
                    )
                    for position, trim_id in enumerate(trim_ids):
                        raw = values[position] if position < len(values) else ""
                        text = clean_value(raw)
                        number, value_unit = numeric_value(text)
                        yield {
                            "trim_id": trim_id,
                            "series_id": candidate.series_id,
                            "parameter_key": key,
                            "group_id": str(group_id),
                            "group_name": clean_group_name,
                            "parameter_name": clean_name,
                            "value_raw": str(raw or ""),
                            "value_text": text,
                            "value_numeric": number,
                            "value_unit": value_unit or declared_unit,
                            "equipment_state": equipment_state(text),
                            "captured_at": captured_at,
                        }

    return trims, rows(), definitions


def sales_rows(candidate: SeriesCandidate, page_html: str, captured_at: str) -> Iterator[dict[str, object]]:
    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.select_one("table")
    if table is None:
        return
    for row in table.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
        if len(cells) < 2 or not re.fullmatch(r"20\d{2}-\d{2}", cells[0]):
            continue
        sales = parse_number(cells[1])
        yield {
            "series_id": candidate.series_id,
            "sales_period": cells[0],
            "sales": int(sales) if sales is not None else "",
            "overall_rank": cells[2] if len(cells) > 2 else "",
            "manufacturer_share": cells[3] if len(cells) > 3 else "",
            "manufacturer_rank": cells[4] if len(cells) > 4 else "",
            "segment_rank": cells[5] if len(cells) > 5 else "",
            "registration_related": cells[6] if len(cells) > 6 else "",
            "sales_url": candidate.sales_url,
            "captured_at": captured_at,
        }


def open_csv_writer(path: Path, fields: list[str], *, compressed: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    file = gzip.open(temporary, "wt", encoding="utf-8", newline="") if compressed else temporary.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    return temporary, file, writer


def build_tables(candidates: list[SeriesCandidate], output_dir: Path, captured_at: str) -> tuple[dict[str, int], list[str]]:
    tables = output_dir / "tables"
    paths = {
        "series": tables / "series.csv",
        "trims": tables / "trims.csv",
        "definitions": tables / "parameter_definitions.csv",
        "parameters": tables / "trim_parameters.csv.gz",
        "sales": tables / "series_month_sales.csv",
    }
    opened = {
        "series": open_csv_writer(paths["series"], SERIES_FIELDS),
        "trims": open_csv_writer(paths["trims"], TRIM_FIELDS),
        "parameters": open_csv_writer(paths["parameters"], TRIM_PARAMETER_FIELDS, compressed=True),
        "sales": open_csv_writer(paths["sales"], SALES_FIELDS),
    }
    counts = {"series": 0, "trims": 0, "parameter_definitions": 0, "trim_parameters": 0, "sales": 0}
    failures: list[str] = []
    all_definitions: OrderedDict[str, dict[str, str]] = OrderedDict()
    try:
        for candidate in candidates:
            option_path = output_dir / "responses" / "options" / f"{candidate.series_id}.json"
            sales_path = output_dir / "responses" / "sales" / f"{candidate.series_id}.html"
            payload: dict[str, object] | None = None
            if option_path.exists():
                try:
                    loaded = json.loads(option_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        payload = loaded
                    else:
                        raise ValueError("参数缓存不是 JSON 对象")
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    failures.append(f"load-options:{candidate.series_id}:{type(exc).__name__}")
            opened["series"][2].writerow(
                {
                    "series_id": candidate.series_id,
                    "series_name": infer_series_name(candidate, payload),
                    "list_price_min_wan": candidate.list_price_min or "",
                    "list_price_max_wan": candidate.list_price_max or "",
                    "body_hints": "|".join(sorted(candidate.body_hints)),
                    "energy_hints": "|".join(sorted(candidate.energy_hints)),
                    "source_url": candidate.source_url,
                    "options_url": candidate.options_url,
                    "sales_url": candidate.sales_url,
                    "captured_at": captured_at,
                }
            )
            counts["series"] += 1
            if payload is not None:
                try:
                    trims, parameters, definitions = option_rows(candidate, payload, captured_at)
                    for trim in trims:
                        opened["trims"][2].writerow(trim)
                        counts["trims"] += 1
                    for parameter in parameters:
                        opened["parameters"][2].writerow(parameter)
                        counts["trim_parameters"] += 1
                    all_definitions.update(definitions)
                except (ValueError, TypeError) as exc:
                    failures.append(f"parse-options:{candidate.series_id}:{type(exc).__name__}")
            if sales_path.exists():
                try:
                    for sale in sales_rows(candidate, sales_path.read_text(encoding="utf-8"), captured_at):
                        opened["sales"][2].writerow(sale)
                        counts["sales"] += 1
                except OSError as exc:
                    failures.append(f"parse-sales:{candidate.series_id}:{type(exc).__name__}")
    finally:
        for _, file, _ in opened.values():
            file.close()

    definition_tmp, definition_file, definition_writer = open_csv_writer(paths["definitions"], PARAMETER_FIELDS)
    try:
        for definition in all_definitions.values():
            definition_writer.writerow(definition)
            counts["parameter_definitions"] += 1
    finally:
        definition_file.close()

    for name, path in paths.items():
        temporary = definition_tmp if name == "definitions" else opened[name][0]
        temporary.replace(path)
    return counts, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="采集 16888 全量在售车型参数与月销量历史")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--captured-at", default=date.today().isoformat())
    parser.add_argument("--delay", type=float, default=1.0, help="相邻请求最小间隔（秒）")
    parser.add_argument("--max-series", type=int, default=0, help="只处理前 N 个车系，适合试运行")
    parser.add_argument("--series-id", action="append", default=[], help="只处理指定车系 ID，可重复传入")
    parser.add_argument("--force-refresh", action="store_true", help="忽略缓存并重新请求")
    parser.add_argument("--build-only", action="store_true", help="停止联网，仅从已缓存响应重建表格")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected_path = args.output_dir / "selected_series.json"
    if args.build_only:
        if not selected_path.exists():
            raise RuntimeError("缺少 selected_series.json，无法识别缓存所属车系")
        candidates = cached_candidates(load_selected_candidates(selected_path), args.output_dir)
        fetch_failures: list[str] = []
    else:
        client = PoliteClient(args.delay)
        candidates = manual_candidates(args.series_id) if args.series_id else discover_candidates(client)
        if args.max_series > 0:
            candidates = candidates[: args.max_series]
        write_json_atomic(selected_path, [candidate_record(candidate) for candidate in candidates])
        fetch_failures = fetch_raw_responses(
            client,
            candidates,
            args.output_dir,
            force_refresh=args.force_refresh,
        )
    if not candidates:
        raise RuntimeError("没有发现可处理车系")

    counts, parse_failures = build_tables(candidates, args.output_dir, args.captured_at)
    manifest = {
        "data_source": "16888.com 车主之家",
        "scope": "已缓存的在售车系、完整配置参数和销量页历史" if args.build_only else "当前公开分类页发现的在售车系、完整配置参数和销量页历史",
        "captured_at": args.captured_at,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_series": len(candidates),
        "counts": counts,
        "failures": fetch_failures + parse_failures,
        "request_delay_seconds": args.delay,
        "build_only": args.build_only,
    }
    write_json_atomic(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
