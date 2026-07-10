# 数据说明

## 来源

当前原始快照为 [China Car Price Index 的公开车型列表](https://chinacarprices.com/models)，抓取日期为 `2026-07-10`。源页面公开展示车型、品牌、动力形式、美元起售价、车身类型、年款、续航、功率和座位数；`scripts/fetch_public_dataset.py` 只提取页面已有字段，并为每条记录保留来源详情页。

该快照仅用于课程项目与技术演示，不代表实时、完整或可用于交易的汽车报价。需要公开发布或商业使用时，应重新核查来源站点条款与数据授权。

## raw

`raw/china_car_prices_snapshot.csv` 是 84 款车型的原始展示字段快照。原始价格以美元记录，不直接修改、不填补缺失参数。更新命令：

```bash
make data
```

## processed

运行 `make spark` 后生成：

- `cars.csv`：Web 和推荐算法直接加载的标准主表；
- `cars.parquet/`：Spark 标准列式输出；
- `stats.json`：价格区间、能源和车身类型统计；
- `metadata.json`：运行时间、Spark 版本、输入校验值、行数和换算率。

处理阶段采用固定演示汇率 `1 USD = 7.20 CNY`，把美元起售价换算为万元。来源没有价格上限时，`price_max_wan` 等于起售价；来源没有销量、热度或油耗时保持为空，推荐算法自动取消相应评分项。
