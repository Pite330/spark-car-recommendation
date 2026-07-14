# 轻量接口约定

MVP 约定健康检查、推荐、车型对比和参数销量分析概览接口。字段调整必须先修改本文档，再同步前端和算法模块。

## 1. 健康检查

### `GET /api/health`

```json
{
  "status": "ok",
  "dataset_loaded": true,
  "car_count": 1744,
  "llm_enabled": false,
  "llm_provider": "deepseek",
  "llm_model": "deepseek-v4-flash"
}
```

## 2. 获取推荐

### `POST /api/recommend`

请求：

```json
{
  "budget_min_wan": 15,
  "budget_max_wan": 20,
  "body_type": "SUV",
  "energy_type": "纯电",
  "brands": [],
  "scenario": "城市通勤",
  "min_seats": 5,
  "min_sales": 500,
  "limit": 5,
  "use_llm": false
}
```

成功响应：

```json
{
  "request_id": "local-001",
  "total_candidates": 18,
  "relaxed_conditions": [],
  "recommendations": [
    {
      "car_id": "car_0001",
      "model_name": "示例车型A",
      "brand": "示例品牌",
      "price_min_wan": 16.98,
      "price_max_wan": 18.98,
      "body_type": "SUV",
      "energy_type": "纯电",
      "sales": 1250,
      "sales_period": "2026-06",
      "normalized_heat": 0.72,
      "data_completeness": 0.83,
      "score": 91.0,
      "matched_factors": [
        "价格符合预算",
        "符合纯电SUV偏好",
        "续航适合城市通勤"
      ],
      "reason": "该车型价格处于预算范围内，并符合纯电SUV和城市通勤需求。",
      "reason_source": "template"
    }
  ]
}
```

规则：

- `score` 由算法模块生成；
- `matched_factors` 只包含数据可证明的事实；
- `min_sales` 可选；填写后只保留销量已知且达到阈值的车型；
- `sales` 是数据快照中的车系月销量，同车系不同能源记录可能共享该值；
- `reason_source` 只能是 `template` 或 `llm`；
- DeepSeek 成功改写时额外返回 `reason_provider: "deepseek"`；
- 大模型失败时仍返回 200，并把 `reason_source` 设置为 `template`。

## 3. 车型对比

### `POST /api/compare`

请求：

```json
{
  "car_ids": ["car_0001", "car_0002"]
}
```

响应中的每辆车只返回数据集中存在的可对比字段。`car_ids` 最少 2 个、最多 3 个。

```json
{
  "cars": [
    {
      "car_id": "car_0001",
      "model_name": "示例车型A",
      "brand": "示例品牌",
      "price_min_wan": 16.98,
      "price_max_wan": 18.98,
      "body_type": "SUV",
      "energy_type": "纯电",
      "seats": 5,
      "range_km": 520,
      "horsepower": 218,
      "trim_count": 8,
      "sales": 1250,
      "sales_period": "2026-06",
      "normalized_heat": 0.72,
      "data_completeness": 0.83
    }
  ]
}
```

前端参数表只显示至少一款车型具有真实值的字段。价格与销量图使用 `price_min_wan` 和 `sales` 的绝对值；`sales` 缺失时显示“暂无”且不补零。完整配置长表中的数百项参数属于配置款粒度，未经过车系级口径整理前不得直接混入此接口。

## 4. 参数销量分析概览

### `GET /api/analysis/overview?limit=187`

读取离线生成的分析结果，不会触发 Spark 计算。`limit` 可选，默认 187，必须是 1 到 500 之间的整数。

```json
{
  "available": true,
  "sales_period": "2026-06",
  "analysis_rows": 425,
  "parameter_definitions": 187,
  "adapter_features": 137,
  "model_features": 98,
  "significant_features": 21,
  "incremental_r2": {
    "elastic_net": 0.04362,
    "random_forest": 0.04842
  },
  "metrics": [
    {
      "key": "baseline_elastic_net",
      "label": "控制变量基线",
      "r2": 0.203563,
      "rmse": 1.942922,
      "mae": 1.545922
    }
  ],
  "top_parameters": [
    {
      "feature_name": "equip_3897ea1e80ef",
      "group_name": "内部配置",
      "parameter_name": "多功能方向盘",
      "parameter_type": "equipment",
      "spearman_rho": -0.202215,
      "fdr_q_value": 0.000939,
      "elastic_net_coefficient": 0.0,
      "random_forest_importance": 0.045318,
      "evidence_strength": "moderate",
      "association_direction": "negative",
      "trend_status": "insufficient_history",
      "excluded_reason": ""
    }
  ],
  "warnings": ["探索性关联，不代表配置参数对销量的因果影响"]
}
```

规则：

- `top_parameters` 优先读取覆盖全部来源参数的统一结果表，并按 `random_forest_importance` 降序返回；未进入模型的参数仍保留在结果尾部；
- 未进入 Adapter 的参数没有模型特征名，接口会使用 `raw:{分组}|{参数名}` 作为稳定展示键，并返回 `not_evaluated`；
- 数值不可用时返回 `null`，文本不可用时返回空字符串；
- 四个分析结果文件全部成功加载时 `available` 为 `true`；任一文件缺失或损坏时接口仍返回 200、`available` 为 `false`，并在 `warnings` 说明原因；
- 分析结果是探索性关联，不能解释为配置变化会因果性地改变销量。

## 5. 错误响应

```json
{
  "error": {
    "code": "INVALID_BUDGET",
    "message": "预算下限不能高于预算上限",
    "field": "budget_min_wan"
  }
}
```

建议状态码：参数错误使用 400，车型不存在使用 404，数据集未加载使用 503，未处理异常使用 500。分析接口的 `limit` 非整数或超出 1 到 500 时返回 `INVALID_LIMIT`。
