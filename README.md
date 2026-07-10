# Spark 汽车购车推荐平台

一个已跑通的消费者购车推荐 MVP：PySpark 离线清洗公开车型快照，确定性算法按预算和偏好筛选评分，Flask 返回 3—5 款可解释推荐，页面支持车型对比和 ECharts 数据统计。大模型只负责可选文字润色，关闭后主链路不受影响。

## 已完成功能

- 16888（车主之家）144 个车系、190 条车系能源记录快照，保留参数页、销量页和抓取日期；
- PySpark 4.0.3 清洗、枚举映射、销量热度归一化、衍生场景标签、CSV/Parquet 输出；
- 输入预算、车身、能源、品牌、场景、座位数；
- 硬性筛选、权重归一化评分、稳定排序和显式条件放宽；
- 3—5 款推荐卡片、匹配分、至少两条数据依据；
- 2—3 款车型参数表和雷达图对比；
- Spark 车型库能源/车身分布图；
- OpenAI 兼容说明接口、超时处理和模板化降级；
- 健康检查、推荐、对比接口及 13 项自动化测试。

## 一键运行

环境要求：Python 3.10+、Java 17+。本机 Java 23 也已验证，Spark 脚本会为其子进程自动设置 Hadoop 兼容开关。

```bash
make setup
make spark
make test
make run
```

本机浏览器打开 <http://127.0.0.1:5000>。仓库已经包含原始快照和本次 Spark 处理结果，日常演示不需要联网；仅在主动更新原始快照时运行：

```bash
make data
make spark
```

如本机下载 PySpark 较慢，可临时使用国内 PyPI 镜像：

```bash
.venv/bin/python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 演示输入

推荐使用 `15—20 万 / SUV / 纯电 / 城市通勤 / 5 座`。当前快照会稳定给出 5 款候选，并显式展示场景或预算放宽记录。也可以关闭所有可选条件验证仅按预算推荐。

## 数据处理证据

- 标准 CSV：`data/processed/cars.csv`
- 标准 Parquet：`data/processed/cars.parquet/`
- Spark 统计：`data/processed/stats.json`
- 运行元数据：`data/processed/metadata.json`

元数据记录 Spark 版本、运行时间、输入 SHA-256、数据源和输入/输出行数。价格为 16888 抓取时公开展示的万元指导价区间，销量为公开销量页的最近月度值；两者都不是实时成交或上牌数据。

## DeepSeek 推荐说明

默认已接入 DeepSeek 官方 OpenAI 兼容接口，模型使用 `deepseek-v4-flash` 并关闭思考模式，适合低延迟地改写短推荐理由：

```bash
cp .env.example .env
```

在不会提交到 Git 的 `.env` 中填写：

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
```

也可以把 Key 单独存入私密文件，通过 `DEEPSEEK_API_KEY_FILE` 指向它。未配置、超时、额度不足、网络失败或返回异常时，接口仍返回 200，并保留算法生成的车型、分数、依据和模板说明。其他 OpenAI 兼容服务仍可通过 `.env.example` 中的通用配置启用。

## 局域网访问

需要同一 Wi-Fi / 局域网内的其他设备访问时，在 `.env` 中设置：

```dotenv
APP_HOST=0.0.0.0
APP_PORT=5050
```

启动 `make run` 后，其他设备访问 `http://<本机局域网IP>:5050`。macOS 的隔空播放接收器通常占用对外的 5000 端口，因此局域网演示默认建议使用 5050。不要把 Flask 开发服务直接暴露到公网；跨网访问应使用反向代理、VPN 或正式 WSGI 服务。

## 项目结构

```text
data/raw/                 原始公开快照（只读）
data/processed/           Spark 可重建结果与统计证据
scripts/                  原始快照更新脚本
src/spark_jobs/           PySpark 清洗与统计
src/recommender/          校验、筛选、评分、放宽和模板原因
src/web/                  Flask、页面、ECharts 和 LLM 适配
tests/                    算法、接口、降级和产物测试
docs/                     MVP、契约、设计和验收记录
```

## 文档

- [MVP 方案](docs/MVP.md)
- [接口约定](docs/api-contract.md)
- [数据字典](docs/data-dictionary.md)
- [16888 数据采集说明](docs/data-acquisition-16888.md)
- [推荐算法](docs/recommendation-design.md)
- [验收记录](docs/acceptance-report.md)
- [课程交付材料填写指南](docs/deliverables-fill-guide.md)
