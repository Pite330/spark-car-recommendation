# Spark 汽车购车推荐平台

面向普通消费者的轻量购车推荐项目。系统使用 PySpark 清洗和整理汽车数据，消费者输入预算、车型、能源类型等条件后，系统返回 3—5 款候选车型、匹配得分和可解释的推荐原因。

## 当前状态

项目处于需求和技术设计阶段，MVP 范围、数据字段、推荐规则、接口约定和四人分工已经确定，尚未开始编写业务代码。

## 核心边界

- 只服务购车消费者；
- 不做用户注册、登录和权限管理；
- 不做汽车厂商经营分析；
- 不做订单、支付和试驾预约；
- 大模型只润色已有推荐依据，不直接决定推荐车型；
- 大模型不可用时，核心推荐链路必须继续运行。

## 最小技术链路

```text
汽车原始数据
    -> PySpark 清洗与特征处理
    -> CSV/Parquet 标准数据集
    -> 条件筛选与加权评分
    -> Flask 轻量接口
    -> 推荐结果与 ECharts 页面
    -> 可选的大模型推荐说明
```

## 文档索引

- [MVP 方案](docs/MVP.md) / [MVP PDF](docs/MVP.pdf)
- [产品需求](docs/product-requirements.md)
- [系统架构](docs/architecture.md)
- [数据字典](docs/data-dictionary.md)
- [推荐算法设计](docs/recommendation-design.md)
- [接口约定](docs/api-contract.md)
- [四人分工与开发计划](docs/team-plan.md)

## 目录结构

```text
spark-car-recommendation/
├── data/
│   ├── raw/               # 原始数据，不直接修改
│   └── processed/         # Spark 处理后的标准数据
├── docs/                  # 产品、技术和协作文档
├── src/
│   ├── spark_jobs/        # PySpark 清洗与统计任务
│   ├── recommender/       # 筛选、评分和推荐原因
│   └── web/               # Flask、页面和可视化
└── tests/                 # 数据、算法和接口测试
```

## 建议开发顺序

1. 确认真实数据集及字段；
2. 完成 Spark 清洗脚本并输出标准数据；
3. 使用固定样例验证筛选和评分算法；
4. 按接口约定接入 Flask 页面；
5. 完成车型对比和必要图表；
6. 主链路稳定后再接入大模型；
7. 按 MVP 验收标准完成联调和答辩演示。
