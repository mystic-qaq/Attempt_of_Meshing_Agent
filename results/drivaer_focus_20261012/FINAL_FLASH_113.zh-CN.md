# DrivAer 0.10 原生对照结果

自由空气单相网格研究；完整几何保留，首层物理高度固定。研究资格与工业 CFD 精度分开。

|案例 / 路线|状态|原生阶段|有效模型试验|合格研究候选|所选 ≥5 层面积|单元数|新增 API 费用上界|
|---|---|---:|---:|---:|---:|---:|---:|
|drivaer_410 / llm|failed|3|3|0|无|—|$0.071285|
|drivaer_410 / deterministic|failed|3|0|0|无|—|$0.000000|

## 全部阶段，包括失败

|案例 / 路线|阶段|类型|动作来源|单元数|≥5 层面积|basic Failed|研究资格|
|---|---:|---|---|---:|---:|---:|---|
|drivaer_410 / llm|1|full|model|1,578,685|48.39%|6|False|
|drivaer_410 / llm|2|full|model|3,933,107|33.63%|0|False|
|drivaer_410 / llm|3|full|model|1,402,884|30.02%|0|False|
|drivaer_410 / deterministic|1|full|deterministic_feedback|4,195,066|43.25%|6|False|
|drivaer_410 / deterministic|2|full|deterministic_feedback|4,028,341|38.29%|0|False|
|drivaer_410 / deterministic|3|full|deterministic_feedback|4,219,007|43.65%|0|False|

## 判断与限制

“明显改善”预先定义为 ≥5 层面积增加至少 10 个百分点、单元增长最多20%，≥1层与三个困难区域不得下降超过2个百分点。每个源几何在本轮研究中的API费用上限$0.50，重试共用。上界不是逐笔账单。

程序化直出未合格时，不能计算“相对合格基线的覆盖增益”。模型修复成合格候选与高覆盖但仍然失败的网格分别报告。取得合格网格不代表阻力或真实y+精度通过。

- drivaer_410：明显优于同预算程序反馈=False；只有模型得到合格候选=False；覆盖差=None个百分点。

### drivaer_410 / llm
停止原因：stage budget exhausted。原生阶段耗时 1838.3s，独立测量 111.6s；完整墙钟时间 2461.4s。

### drivaer_410 / deterministic
停止原因：stage budget exhausted。原生阶段耗时 1876.2s，独立测量 178.3s；完整墙钟时间 2167.0s。

## 输入排除
