# 轻量接口约定

MVP 只约定健康检查、推荐和车型对比三个接口。字段调整必须先修改本文档，再同步前端和算法模块。

## 1. 健康检查

### `GET /api/health`

```json
{
  "status": "ok",
  "dataset_loaded": true,
  "car_count": 190,
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
      "body_type": "SUV",
      "energy_type": "纯电",
      "seats": 5,
      "range_km": 520
    }
  ]
}
```

## 4. 错误响应

```json
{
  "error": {
    "code": "INVALID_BUDGET",
    "message": "预算下限不能高于预算上限",
    "field": "budget_min_wan"
  }
}
```

建议状态码：参数错误使用 400，车型不存在使用 404，数据集未加载使用 503，未处理异常使用 500。
