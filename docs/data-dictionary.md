# 数据字典

数据字典以最终选定的真实数据集为准。下表是 MVP 的标准字段约定，原始字段应在 Spark 清洗阶段映射到这些名称。

## 1. 车型主表

| 字段 | 类型 | 必需 | 示例 | 处理规则 |
| --- | --- | --- | --- | --- |
| `car_id` | string | 是 | `car_0001` | 唯一且非空；没有原始 ID 时稳定生成 |
| `series_id` | string | 是 | `128913` | 16888 车系 ID；同一车系的不同能源记录共享该值 |
| `model_name` | string | 是 | `示例车型A` | 去除首尾空格；不可为空 |
| `brand` | string | 是 | `示例品牌` | 统一中英文、大小写和别名 |
| `price_min_wan` | double | 是 | `15.98` | 单位统一为万元；必须大于 0 |
| `price_max_wan` | double | 否 | `18.98` | 缺失时可等于最低指导价 |
| `body_type` | string | 是 | `SUV` | 映射为轿车、SUV、MPV 等标准枚举 |
| `energy_type` | string | 是 | `纯电` | 映射为燃油、纯电、插混、增程等枚举 |
| `seats` | integer | 否 | `5` | 小于 2 或大于 9 时标记异常 |
| `range_km` | double | 否 | `520` | 仅适用于有续航字段的车型 |
| `fuel_consumption` | double | 否 | `6.5` | 统一为 L/100km；不适用时为空 |
| `horsepower` | integer | 否 | `218` | 来源标注功率；仅用于展示与车型对比 |
| `model_year` | integer | 否 | `2024` | 来源页面的车型年款 |
| `sales` | integer | 否 | `12345` | 负数无效；需要记录统计周期 |
| `sales_period` | string | 否 | `2026-06` | 最近月销量所属月份；格式为 `YYYY-MM` |
| `trim_count` | integer | 否 | `8` | 当前车系能源分组内参与聚合的配置数量 |
| `heat_score` | double | 否 | `0.82` | 归一化到 0—1；可由销量生成 |
| `source` | string | 是 | `dataset_name` | 记录数据来源 |
| `updated_at` | date | 否 | `2026-07-10` | 记录数据时间，避免把旧价格当实时价格 |
| `source_url` | string | 否 | `https://...` | 当前记录的来源详情页 |
| `options_url` | string | 否 | `https://.../options/` | 公开车型参数页 |
| `sales_url` | string | 否 | `https://xl.16888.com/...` | 公开车系销量页 |

## 2. 推荐衍生字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `price_mid_wan` | double | 最低价和最高价的中点，用于预算匹配 |
| `normalized_heat` | double | 销量或热度标准化结果 |
| `scenario_tags` | array/string | 根据已有参数生成的通勤、家庭、长途等规则标签 |
| `data_completeness` | double | 当前车型可用字段完整度，用于质量提示，不直接替代匹配得分 |

## 3. 缺失值原则

- 车型名称、品牌、价格、车身类型和能源类型缺失时，不进入推荐主表；
- 座位数、续航、油耗、销量等可选字段缺失时保留车型，但取消相应评分；
- 不得使用大模型或主观猜测补齐车辆参数；
- 使用统计填充时，必须在 Spark 脚本和报告中记录方法。

## 4. 数据版本

每次生成标准数据时记录：原始文件校验值、处理脚本版本、处理时间、输入行数、输出行数、删除行数和主要异常数量。

当前实现直接使用 16888 页面展示的万元指导价区间，不做汇率换算。车系存在多个能源版本时按能源拆分，同一车系的能源记录共享车系月销量；归一化热度由月销量取 `log(sales + 1)` 后除以全表最大值生成。来源未稳定提供的续航、油耗等字段保持为空。

## 5. 完整配置参数扩展表

完整参数数据由 `scripts/fetch_16888_full_options.py` 生成，不替换上面的消费者推荐主表。

### 5.1 配置款表 `trims.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trim_id` | string | 16888 配置款 ID，对应 `/c/{trim_id}/options/` |
| `series_id` | string | 所属车系 ID |
| `trim_name` | string | 完整配置款名称 |
| `model_year` | string | 年代款 |
| `status` | string | 来源站点原始在售状态码 |
| `energy_type_raw` | string | 来源站点能源类型原值 |
| `displacement` | string | 排量/动力标识原值 |
| `transmission` | string | 来源站点变速箱标识 |
| `drive_style` | string | 驱动方式 |
| `body_structure` | string | 车身结构 |
| `seats_raw` | string | 座位数原值 |

### 5.2 参数字典 `parameter_definitions.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `parameter_key` | string | 分组 ID、分组名称和参数名称组成的稳定键 |
| `group_id` | string | 来源接口的参数分组 ID |
| `group_name` | string | 基本参数、车身、安全装备、玻璃/后视镜、高科技配置等分组 |
| `parameter_name` | string | 来源参数名称，完整保留 |
| `declared_unit` | string | 从参数名称括号中提取的单位 |

### 5.3 配置款参数长表 `trim_parameters.csv.gz`

每一行表示一个配置款的一个参数。`value_raw` 保留来源值，`value_text` 负责清理 HTML 实体；只有完整单一数值才写入 `value_numeric`，尺寸、轮胎规格和前/后组合配置不会被错误拆成数值。

`equipment_state` 取值为 `standard`、`optional`、`mixed`、`missing` 或 `value`，分别表示标配、选配、组合状态、缺失和普通文本/数值。原始值始终保留，归一化结果不能代替来源证据。

### 5.4 月销量表 `series_month_sales.csv`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `series_id` | string | 车系 ID；销量无法直接细分到配置款 |
| `sales_period` | string | 月份，格式为 `YYYY-MM` |
| `sales` | integer | 月销量 |
| `overall_rank` | string | 当月销量排名 |
| `manufacturer_share` | string | 占厂商份额原值 |
| `manufacturer_rank` | string | 厂商内部排名 |
| `segment_rank` | string | 同级车型排名 |
| `registration_related` | string | 来源页面的上牌相关说明 |

## 6. 参数销量分析产物

`data/processed/analysis/analysis_dataset.parquet` 每行表示一个车系在统一销量月份的分析样本。目标字段为 `target_sales` 和 `target_log_sales`；控制字段包括 `brand`、`level_name`、`energy_type`、`body_structure`、`price_median_wan`、`model_year_max` 和 `trim_count`。

参数特征采用稳定哈希列名，`num_` 表示车系内数值中位数，`equip_` 表示车系内装备覆盖分。哈希列与中文参数名称的映射以 `parameter_quality.csv` 为准，禁止根据哈希名猜测参数含义。
