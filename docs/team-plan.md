# 四人模块化分工与开发计划

## 1. 分工原则

四人各自负责一个边界完整、能够独立讲解和验收的子项目，不按代码行数机械拆文件。每个子项目都包含五类工作：功能代码、自动化或手工测试、对应设计文档、运行证据、答辩讲解。

四人贡献比例统一为 25%。代码行数只用于发现明显失衡，不直接决定贡献比例；数据解析、算法设计、页面调试和集成交付的难度不能用物理行数等价衡量。

## 2. 四个子项目

| 成员 | 负责子项目 | 责任边界 | 必须交付 |
| --- | --- | --- | --- |
| 成员 A | 数据采集与 Spark 数据工程 | 从 16888 生成原始快照；完成 Spark 清洗、字段映射、特征和统计；保证处理结果可重建 | 采集脚本、Spark 脚本、原始/标准数据、数据测试、数据字典、采集说明、1746/1744 运行证据 |
| 成员 B | 推荐算法与 DeepSeek 说明 | 完成请求校验、硬性筛选、加权评分、条件放宽、模板原因和 DeepSeek 降级；保证结果确定且可解释 | 推荐模块、大模型适配、算法与降级测试、权重说明、推荐设计文档、推荐演示 |
| 成员 C | Flask 接口、系统集成与文档交付 | 加载标准数据；封装健康、推荐和对比接口；组织端到端联调；维护 Markdown/PDF 构建和项目交付文档 | Flask/装载模块、API 测试、接口契约、架构与验收文档、PDF 转换脚本、部署及局域网说明 |
| 成员 D | 前端交互与数据可视化 | 完成条件表单、推荐卡片、放宽提示、车型对比、雷达图、统计图和响应式页面；保证演示可用 | HTML/CSS/JavaScript、ECharts 图表、页面手工测试、页面截图、用户手册和前端演示 |

最终填写材料时，把 A—D 替换为真实姓名和学号。每人主讲自己负责的子项目，并回答该模块的设计、实现、测试和限制问题。

## 3. 工作量平衡依据

| 成员 | 代码量参考 | 测试责任 | 文档与证据责任 | 综合工作量判断 |
| --- | ---: | --- | --- | --- |
| 成员 A | 约 700 行 | 数据产物测试 | 数据字典、采集说明、Spark 日志和统计截图 | 代码较多，但主要是采集解析和字段映射；形成一个完整数据链路 |
| 成员 B | 约 550 行 | 推荐与 LLM 测试 | 算法权重、放宽策略、降级说明和推荐演示 | 代码量适中，算法设计、边界判断和可解释性要求较高 |
| 成员 C | 约 500 行 | API 与端到端联调 | 接口、架构、验收、README、PDF 构建和部署说明 | 代码较少，但承担跨模块集成和主要交付材料维护 |
| 成员 D | 约 580 行 | 浏览器手工测试 | 用户手册、页面截图、可视化和现场演示 | 代码量适中，页面调试、适配和演示准备工作较多 |

四人的物理代码量并不完全相同，但加上测试、文档、运行证据和答辩职责后，工作量接近。禁止为了让行数相同而拆分同一核心文件或增加无效代码。

## 4. 文件所有权

### 成员 A：数据采集与 Spark 数据工程

- `scripts/fetch_16888_dataset.py`
- `src/spark_jobs/clean_cars.py`
- `src/spark_jobs/__init__.py`
- `tests/test_processed_data.py`
- `data/raw/`、`data/processed/`
- `docs/data-acquisition-16888.md`、`docs/data-dictionary.md`、`data/README.md`

### 成员 B：推荐算法与 DeepSeek 说明

- `src/recommender/`
- `src/web/llm.py`
- `tests/test_recommender.py`、`tests/test_llm.py`
- `docs/recommendation-design.md`

### 成员 C：Flask 接口、系统集成与文档交付

- `src/web/app.py`、`src/recommender/loader.py`
- `tests/test_api.py`、`tests/conftest.py`
- `scripts/markdown_to_pdf.py`、`Makefile`
- `docs/api-contract.md`、`docs/architecture.md`、`docs/acceptance-report.md`
- `README.md`、`docs/MVP.md`、`docs/MVP.pdf`、`docs/deliverables-fill-guide.md`

### 成员 D：前端交互与数据可视化

- `src/web/templates/index.html`
- `src/web/static/css/app.css`
- `src/web/static/js/app.js`
- 页面截图、用户使用手册和答辩中的页面演示部分

## 5. 互审与交接

| 交接方向 | 固定交付内容 |
| --- | --- |
| A → B | `cars.csv`、字段定义、缺失值和热度说明 |
| B → C | 推荐函数输入输出、错误类型、DeepSeek 降级行为 |
| C → D | API 契约、请求示例、响应示例和错误响应 |
| D → A | 页面暴露的数据问题、字段展示需求和截图反馈 |

成员 A 评审 D，B 评审 A，C 评审 B，D 评审 C。评审人可以提出修改，但核心文件仍由对应负责人完成，避免责任不清。

## 6. 开发阶段

### 阶段一：接口冻结

- A 提供标准数据字段和样例行；
- B 提供推荐函数输入输出；
- C 固化 JSON API 契约；
- D 基于固定 JSON 完成页面原型。

### 阶段二：子项目独立实现

- 四人只修改自己负责的核心文件；
- 每个子项目同步完成测试、模块文档和演示证据；
- 字段或接口变化通过对应文档通知上下游。

### 阶段三：端到端联调

- A、B 联调标准数据与推荐算法；
- B、C 联调推荐模块与 Flask；
- C、D 联调接口与页面；
- 四人共同验证非法预算、候选不足、字段缺失和大模型失败。

### 阶段四：提交与答辩

- 每人整理自己子项目的截图、测试结果和答辩页；
- C 负责统一生成 PDF 和检查材料一致性，但内容由四人分别提供；
- 每人主讲约四分之一时间，贡献比例均填写 25%。

## 7. 代码量复核

需要复核是否出现明显失衡时执行：

```bash
find scripts src tests -type f \
  \( -name '*.py' -o -name '*.js' -o -name '*.html' -o -name '*.css' \) \
  -not -path '*/__pycache__/*' -print0 \
  | xargs -0 wc -l
```

统计时排除第三方 `src/web/static/vendor/echarts.min.js`。复核的目标是发现某人工作量明显不足或过重，不是把四个人调整到完全相同的行数。
