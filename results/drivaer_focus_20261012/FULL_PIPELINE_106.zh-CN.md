# DrivAer 0.10 原生对照结果

自由空气单相网格研究；完整几何保留，首层物理高度固定。研究资格与工业 CFD 精度分开。

|案例 / 路线|状态|原生阶段|有效模型试验|合格研究候选|所选 ≥5 层面积|单元数|新增 API 费用上界|
|---|---|---:|---:|---:|---:|---:|---:|
|drivaer_318 / llm|failed|0|0|0|无|—|$0.029225|
|drivaer_318 / deterministic|failed|4|0|0|无|—|$0.000000|
|drivaer_410 / llm|failed|4|4|0|无|—|$0.128991|
|drivaer_410 / deterministic|failed|4|0|0|无|—|$0.000000|

## 全部阶段，包括失败

|案例 / 路线|阶段|类型|动作来源|单元数|≥5 层面积|basic Failed|研究资格|
|---|---:|---|---|---:|---:|---:|---|
|drivaer_318 / deterministic|1|full|deterministic_feedback|1,157,155|33.50%|0|False|
|drivaer_318 / deterministic|2|full|deterministic_feedback|1,188,043|33.61%|0|False|
|drivaer_318 / deterministic|3|full|deterministic_feedback|1,186,579|35.30%|6|False|
|drivaer_318 / deterministic|4|full|deterministic_feedback|1,185,214|34.02%|6|False|
|drivaer_410 / llm|1|full|model|1,329,309|29.75%|6|False|
|drivaer_410 / llm|2|full|model|1,505,817|30.33%|0|False|
|drivaer_410 / llm|3|full|model|1,375,248|29.05%|0|False|
|drivaer_410 / llm|4|full|model|1,451,450|30.86%|0|False|
|drivaer_410 / deterministic|1|full|deterministic_feedback|1,321,124|29.73%|0|False|
|drivaer_410 / deterministic|2|full|deterministic_feedback|1,388,961|31.20%|0|False|
|drivaer_410 / deterministic|3|full|deterministic_feedback|1,369,689|33.08%|1|False|
|drivaer_410 / deterministic|4|full|deterministic_feedback|1,403,117|32.46%|0|False|

## 判断与限制

“明显改善”预先定义为 ≥5 层面积增加至少 10 个百分点、单元增长最多20%，≥1层与三个困难区域不得下降超过2个百分点。每个源几何在本轮研究中的API费用上限$0.50，重试共用。上界不是逐笔账单。

程序化直出未合格时，不能计算“相对合格基线的覆盖增益”。模型修复成合格候选与高覆盖但仍然失败的网格分别报告。取得合格网格不代表阻力或真实y+精度通过。

- drivaer_318：明显优于同预算程序反馈=False；只有模型得到合格候选=False；覆盖差=None个百分点。
- drivaer_410：明显优于同预算程序反馈=False；只有模型得到合格候选=False；覆盖差=None个百分点。

### drivaer_318 / llm
停止原因：ValueError: no committed warm-start repair: None。原生阶段耗时 0.0s，独立测量 0.0s；完整墙钟时间 143.1s。

### drivaer_318 / deterministic
停止原因：stage budget exhausted。原生阶段耗时 1768.8s，独立测量 87.2s；完整墙钟时间 1924.4s。

### drivaer_410 / llm
停止原因：stage budget exhausted。原生阶段耗时 2007.3s，独立测量 98.4s；完整墙钟时间 2703.3s。

### drivaer_410 / deterministic
停止原因：stage budget exhausted。原生阶段耗时 1802.6s，独立测量 99.1s；完整墙钟时间 1974.2s。

## 输入排除
