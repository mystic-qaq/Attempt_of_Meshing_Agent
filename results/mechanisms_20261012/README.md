# 原生间隙工具集成验证（2026-10-12）

这是一个具有0.06m狭槽的匿名、封闭、单连通 U 形挤出体，**属于合成工具测试，不是工业案例或模型反馈实验**。没有部件划分、没有付费模型调用，也没有新增 DrivAer 轮次。

两次 stock OpenFOAM v2412 原生生成使用相同输入、全局表面level3、8进程和100万单元预算。层生成关闭，唯一新增干预是在匿名坐标盒中设置 gapLevel (6 3 4)、gapMode outside。原始输入哈希前后相同。

| 测量 | 无 gap 控制 | 有 gap 控制 |
|---|---:|---:|
| 实际总体单元数 | 71,482 | 94,255 |
| 原生 basic Failed | 0 | 0 |
| 指定间隙 ROI 内单元数 | 1,026 | 6,099 |
| ROI 单元跨度的体积加权95分位 | 16.23 mm | 7.92 mm |
| ROI 单元最大跨度 | 16.29 mm | 21.96 mm |

最大值没有同步改善，因此不能概括为“所有单元都变小、质量全面变好”。全域单元增加31.86%，指定区域的体积分布显示分辨率增强；该结果证明控件实际生效，未证明层覆盖、几何保真全部门槛或 CFD 物理精度提升。

ROI：(-0.025,-0.1,-0.1)..(0.025,0.2,0.1)m。读取完整原生体网格、核对总单元数，并验证五个 polyMesh 文件在测量前后哈希相同。权重使用中心落在 ROI 内的整单元体积，不精确裁剪 ROI 边界。

[原生结果与实际 spec](native_gap_smoke.json) · [独立 ROI 测量](native_gap_roi.json)。

从源码复现（必须使用新输出目录）：

```bash
python scripts/native_gap_smoke.py /absolute/new_gap_test --of-root /absolute/openfoam2412 --n-procs 8
python scripts/measure_gap_smoke.py /absolute/new_gap_test
```

这些命令不调用大模型。正式 Agent 的当前软件检查与测试记录见 [机制改进说明](../../docs/MECHANISMS.zh-CN.md)。真实工程网格仍需后续独立验证。
