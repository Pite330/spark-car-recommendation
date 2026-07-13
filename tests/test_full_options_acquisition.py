from __future__ import annotations

from scripts.fetch_16888_full_options import (
    SeriesCandidate,
    clean_value,
    equipment_state,
    numeric_value,
    option_rows,
    sales_rows,
)


def sample_candidate() -> SeriesCandidate:
    return SeriesCandidate("57232", "奥迪A6L", 32.29, 65.68, {"中大型车"}, set())


def test_clean_and_classify_parameter_values():
    assert clean_value("主：●&nbsp;副：○") == "主：● 副：○"
    assert equipment_state("主：● 副：○") == "mixed"
    assert equipment_state("●") == "standard"
    assert equipment_state("-") == "missing"
    assert numeric_value("32.29万") == ("32.29", "万")
    assert numeric_value("5038×1886×1475") == ("", "")


def test_option_rows_preserve_every_trim_parameter_pair():
    payload = {
        "ret": "ok",
        "data": {
            "arrCar": [
                {
                    "car_id": "217370",
                    "car_name": "奥迪A6L 2026款 测试型",
                    "decade": "2026",
                    "status": "99",
                    "fueltype": "汽油",
                    "displacement": "2.0T",
                    "transmission": 2,
                    "driveStyle": "四驱",
                    "body_structure": "三厢车",
                    "seatnum": "●5",
                },
                {
                    "car_id": "219222",
                    "car_name": "奥迪A6L 2026款 另一型",
                    "decade": "2026",
                    "status": "99",
                    "fueltype": "汽油",
                },
            ],
            "arrConfig": {
                "0": {
                    "基本参数": {
                        "厂商指导价(元)": ["42.79万", "32.29万"],
                        "最高车速(km/h)": ["250", "230"],
                    }
                },
                "6": {"安全装备": {"主/副驾驶座安全气囊": ["主：●&nbsp;副：●", "-"]}},
            },
        },
    }

    trims, parameter_iterator, definitions = option_rows(sample_candidate(), payload, "2026-07-10")
    parameters = list(parameter_iterator)

    assert len(trims) == 2
    assert trims[0]["options_url"] == "https://www.16888.com/c/217370/options/"
    assert len(definitions) == 3
    assert len(parameters) == 6
    assert parameters[0]["value_numeric"] == "42.79"
    assert parameters[4]["equipment_state"] == "standard"
    assert parameters[5]["equipment_state"] == "missing"


def test_sales_rows_keep_monthly_history():
    page = """
    <table>
      <tr><th>时间</th><th>月销量(辆)</th></tr>
      <tr><td>2026-06</td><td>7095</td><td>70</td><td>25.65%</td><td>1</td><td>3</td><td>--</td></tr>
      <tr><td>2026-05</td><td>8709</td><td>45</td><td>27.49%</td><td>1</td><td>3</td><td>全国上牌数据</td></tr>
    </table>
    """

    rows = list(sales_rows(sample_candidate(), page, "2026-07-10"))

    assert [row["sales_period"] for row in rows] == ["2026-06", "2026-05"]
    assert rows[0]["sales"] == 7095
    assert rows[1]["manufacturer_share"] == "27.49%"
