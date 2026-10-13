# DrivAer 0.10 原生对照结果

自由空气单相网格研究；完整几何保留，首层物理高度固定。研究资格与工业 CFD 精度分开。

|案例 / 路线|状态|原生阶段|有效模型试验|合格研究候选|所选 ≥5 层面积|单元数|新增 API 费用上界|
|---|---|---:|---:|---:|---:|---:|---:|
|drivaer_318 / llm|failed|5|4|0|无|—|$0.100589|
|drivaer_318 / deterministic|failed|4|0|0|无|—|$0.000000|
|drivaer_410 / llm|failed|6|2|0|无|—|$0.166391|
|drivaer_410 / deterministic|failed|4|0|0|无|—|$0.000000|

## 全部阶段，包括失败

|案例 / 路线|阶段|类型|动作来源|单元数|≥5 层面积|basic Failed|研究资格|
|---|---:|---|---|---:|---:|---:|---|
|drivaer_318 / llm|1|snap|program_initial_plan|762,260|—|0|False|
|drivaer_318 / llm|2|snap|model|782,425|—|0|False|
|drivaer_318 / llm|3|snap|model|1,586,316|—|0|False|
|drivaer_318 / llm|4|snap|model|792,128|—|0|False|
|drivaer_318 / llm|5|snap|model|763,075|—|0|False|
|drivaer_318 / deterministic|1|snap|program_initial_plan|763,009|—|0|False|
|drivaer_318 / deterministic|2|snap|deterministic_feedback|763,069|—|0|False|
|drivaer_318 / deterministic|3|snap|deterministic_feedback|762,833|—|0|False|
|drivaer_318 / deterministic|4|snap|deterministic_feedback|2,484,017|—|0|False|
|drivaer_410 / llm|1|snap|program_initial_plan|945,165|—|0|False|
|drivaer_410 / llm|2|snap|model|1,035,069|—|0|False|
|drivaer_410 / llm|3|snap|deterministic_feedback|945,275|—|0|False|
|drivaer_410 / llm|4|snap|deterministic_feedback|945,350|—|0|False|
|drivaer_410 / llm|5|snap|model|1,601,150|—|0|False|
|drivaer_410 / llm|6|snap|deterministic_feedback|2,530,012|—|0|False|
|drivaer_410 / deterministic|1|snap|program_initial_plan|944,709|—|0|False|
|drivaer_410 / deterministic|2|snap|deterministic_feedback|944,709|—|0|False|
|drivaer_410 / deterministic|3|snap|deterministic_feedback|946,087|—|0|False|
|drivaer_410 / deterministic|4|snap|deterministic_feedback|2,529,947|—|0|False|

## 判断与限制

“明显改善”预先定义为 ≥5 层面积增加至少 10 个百分点、单元增长最多20%，≥1层与三个困难区域不得下降超过2个百分点。每个源几何在本轮研究中的API费用上限$0.50，重试共用。上界不是逐笔账单。

程序化直出未合格时，不能计算“相对合格基线的覆盖增益”。模型修复成合格候选与高覆盖但仍然失败的网格分别报告。取得合格网格不代表阻力或真实y+精度通过。

- drivaer_318：明显优于同预算程序反馈=False；只有模型得到合格候选=False；覆盖差=None个百分点。
- drivaer_410：明显优于同预算程序反馈=False；只有模型得到合格候选=False；覆盖差=None个百分点。

### drivaer_318 / llm
停止原因：model stopped: The snap-stage rejection is a native non-manifold body-boundary defect (a point/edge shared by disconnected face fans) produced when snappyHexMesh snaps a surface cell grid comparable to or coarser than the preserved input tessellation onto near-tangent/sliver native polygons on a featureless, gap-free panel. Since the source triangles are preserved and cannot be edited, and no documented snap configuration nor surface refinement finer than the native polygons removed it, this is an intrinsic-topology dead end rather than a recoverable parameter fault.。原生阶段耗时 1873.8s，独立测量 52.7s；完整墙钟时间 2416.9s。

### drivaer_318 / deterministic
停止原因：proposal rejected without spending a native stage: proposed native stage already measured。原生阶段耗时 1514.8s，独立测量 58.1s；完整墙钟时间 1600.5s。

### drivaer_410 / llm
停止原因：stage budget exhausted。原生阶段耗时 2624.1s，独立测量 83.1s；完整墙钟时间 3422.9s。

### drivaer_410 / deterministic
停止原因：proposal rejected without spending a native stage: proposed native stage already measured。原生阶段耗时 1607.4s，独立测量 58.5s；完整墙钟时间 1691.6s。

## 输入排除
