"""Aggregate frozen development episodes without resetting source budgets or hiding failures."""
import argparse
from pathlib import Path
from cfdmesh.io import read_json,write_json,sha256
from cfdmesh.scientific_advisor import geometry_spend
from cfdmesh.drivaer import research_eligible,regional_layers,clear_gain


def report_study(base,out):
    runs=[];attempts=[];sources={};excluded=[];baselines=[]
    for root in sorted(base.glob('campaign*')):
        if not (root/'protocol.json').exists():continue
        protocol=read_json(root/'protocol.json')
        for folder in sorted((root/'runs').glob('*')) if (root/'runs').exists() else []:
            if not (folder/'agent_run.json').exists():continue
            data=read_json(folder/'agent_run.json')
            if data['status']=='running':raise ValueError('report requires terminal native episodes')
            source,total,own=geometry_spend(folder)
            sources[source]=max(total,sources.get(source,0.))
            entry=dict(episode=root.name,arm=data['arm'],source_sha256=source,status=data['status'],
                stage_count=len(data['rounds']),native_seconds=sum(r['native']['seconds'] for r in data['rounds']),
                model_trials=sum(r['decision']['source']=='model' for r in data['rounds']),
                selected=data.get('selected'),stop_reason=data.get('stop_reason'),own_usd_ceiling=own,
                source_mutated=data['source_mutated'],code_sha256=data['code_sha256'],
                protocol_sha256=sha256(root/'protocol.json'),warm_start=bool(data.get('warm_start')),
                actor_model=data.get('profile',{}).get('model','deepseek-flash'),study_kind=protocol.get('study_kind'),
                full_pipeline_trials=sum(r['stage']=='full' for r in data['rounds']),
                user_interruption=data.get('user_interruption'),
                resource_calibration=data.get('resource_calibration'),
                stop_decision=data.get('stopped_decision'),
                initial_spec_origin=protocol.get('initial_spec_origin') or next((c.get('initial_spec_origin') for c in protocol['cases'] if c['source_sha256']==source),None))
            runs.append(entry)
            for r in data['rounds']:
                q=r['evidence'].get('quality') or {}
                attempts.append(dict(episode=root.name,arm=data['arm'],round=r['round'],stage=r['stage'],
                    decision_source=r['decision']['source'],source_sha256=source,
                    native_case=r['native']['case'],cells=q.get('metrics',{}).get('cells'),
                    basic_failed=q.get('n_failed'),quality_accepted=q.get('accepted'),
                    quality_reasons=q.get('reasons'),fidelity_accepted=r['evidence']['fidelity']['accepted'],
                    coverage_ge5=r['evidence']['layers'].get('coverage'),research_eligible=r['research_eligible'],
                    layer_design=r.get('layer_design'),regional_layers=r['regional_layers'],reasons=r['evidence']['reasons'],
                    native_error=r['native'].get('error'),quality_metrics=q.get('metrics',{}),
                    executed_actions=r['decision'].get('executed_actions'),
                    resolved_measured_actions=r['decision'].get('resolved_measured_actions'),
                    native_seconds=r['native']['seconds']))
    for pure in sorted(base.glob('program_one_shot*/agent_run.json')):
        data=read_json(pure);r=data['rounds'][0];e=r['evidence'];q=e['quality'];layer=e['layers']
        if data['status']=='running':raise ValueError('program baseline is still running')
        baseline=dict(name=pure.parent.name,source_sha256=data['source_sha256'],code_sha256=data['code_sha256'],
            native_case=r['native']['case'],cells=q['metrics']['cells'],basic_failed=q['n_failed'],
            coverage_ge5=layer.get('coverage'),coverage_ge1=1-layer.get('area_fraction_by_layers',{}).get('0',1.),
            research_eligible=research_eligible(e,r['native'],data['config']['budget']),reasons=e['reasons'],
            model_used=False,source_mutated=data['source_mutated'],native_seconds=r['native']['seconds'])
        baseline['layer_design']=r.get('layer_design')
        if not baseline['layer_design'] and data.get('flow'):
            from cfdmesh.layer_design import measure_layer_design
            from cfdmesh.case_builder import MeshSpec
            baseline['layer_design']=measure_layer_design(r['native']['case'],MeshSpec.from_dict(r['spec']),data['flow'])
        import numpy as np
        from types import SimpleNamespace
        geom=SimpleNamespace(mesh=SimpleNamespace(bounds=np.array(data['geometry_audit']['bbox'])))
        baseline['regional_layers']=regional_layers(r['native']['case'],geom)
        baselines.append(baseline)
    for prep in sorted(base.glob('preparation*/preparation.json')):
        data=read_json(prep)
        for inp in data['inputs']:
            if inp.get('error') or not inp.get('native',{}).get('accepted'):
                excluded.append(dict(preparation=prep.parent.name,source_sha256=inp['source_sha256'],
                    source=inp['source'],native=inp.get('native'),error=inp.get('error'),
                    automatic_plan_certified=inp.get('automatic_initial_certification',{}).get('ok')))
    comparisons=[]
    for baseline in baselines:
        matched=[r for r in runs if r['arm']=='llm' and r['actor_model']=='deepseek-flash' and not r.get('user_interruption') and r['source_sha256']==baseline['source_sha256']]
        ref=dict(baseline,coverage=baseline['coverage_ge5'])
        comparisons.append(dict(baseline=baseline['name'],source_sha256=baseline['source_sha256'],
            clear_qualified_gain=any(clear_gain(r.get('selected'),ref) for r in matched),
            repaired_invalid_baseline=not baseline['research_eligible'] and any(r.get('selected') for r in matched),
            interpretation='development comparisons include extra computation; a repair does not establish generalization or isolated LLM gain'))
    gain=any(c['clear_qualified_gain'] for c in comparisons)
    primary=next((b for b in baselines if b['name']=='program_one_shot'),None)
    result=dict(runs=runs,attempts=attempts,pure_program_baseline=primary,pure_program_baselines=baselines,
        baseline_comparisons=comparisons,source_api_usd_ceiling=sources,
        excluded_inputs=excluded,clear_improvement_demonstrated=gain,
        hidden_reasoning_exported=False,physical_accuracy='unverified',
        interpretation='development study; old-template controls differ from the true automatic baseline; excluded and repeated inputs are not independent successes')
    # A valid model candidate alone is a repair result, not a numerical gain over an invalid baseline.
    lines=['# DrivAer 研究改造与原生验证','',
        '新研究按源几何共用 $0.50 API 上限，所有版本和失败调用累计。费用是含未知超时保留额的保守上界，不是账单。',
        '完整源几何保留，固定自由空气 +X / +Z 工况与首层高度；未验证真实阻力、真实 y+ 或道路/车轮运动。','',
        '## 纯程序化基线','']
    for baseline in baselines:
        lines += [f'{baseline["name"]}：无模型初始化、无旧模型模板的一次完整原生生成：≥5 层面积 {baseline["coverage_ge5"]*100:.2f}%，≥1 层面积 {baseline["coverage_ge1"]*100:.2f}%，{int(baseline["cells"]):,} 单元，basic Failed={baseline["basic_failed"]}，研究资格={baseline["research_eligible"]}。',
            '',*['- '+x for x in baseline['reasons']],'']
    lines += ['## 所有路线','',
        '|实验|路线 / 模型|新原生试验|其中完整流水线|模型执行试验|合格候选|API 费用上界|',
        '|---|---|---:|---:|---:|---|---:|']
    for r in runs:lines.append(f'|{r["episode"]}|{r["arm"]} / {r["actor_model"]}|{r["stage_count"]}|{r["full_pipeline_trials"]}|{r["model_trials"]}|{bool(r["selected"])}|${r["own_usd_ceiling"]:.6f}|')
    lines += ['', '冷启动 campaign 与 warm 延续采用历史模型初始模板；它们不能冒充纯程序化直出。延续属于工具修正后的开发实验，不是独立留出案例。复制已有诊断不计作新 native 阶段，旧阶段在原实验中保留计数。','',
        '完整流水线试验包含细化、吸附和加层三个子阶段，不能与一次 snap-only 当成相同计算成本；各版本累计耗时与模型费用均保留。追加模型开发路线不冒充同预算独立对照。','',
        '## 全部真实阶段','',
        '|实验 / 路线|轮次|阶段|动作来源|单元数|≥5 层面积|basic Failed|质量接受|研究资格|',
        '|---|---:|---|---|---:|---:|---:|---|---|']
    for r in attempts:
        cov=f'{r["coverage_ge5"]*100:.2f}%' if r['coverage_ge5'] is not None else '未加层'
        cells=f'{int(r["cells"]):,}' if r['cells'] else '缺失'
        lines.append(f'|{r["episode"]} / {r["arm"]}|{r["round"]}|{r["stage"]}|{r["decision_source"]}|{cells}|{cov}|{r["basic_failed"]}|{r["quality_accepted"]}|{r["research_eligible"]}|')
    lines += ['','## 原始边界层设计','',
        '|实验 / 路线 / 轮次|C1|C5|原目标8层覆盖|实际厚度/原目标 p50|有层但低于半厚度面积|',
        '|---|---:|---:|---:|---:|---:|']
    for r in attempts:
        d=r.get('layer_design') or {}
        if not d.get('available'):continue
        median=(d.get('stack_ratio_area_quantiles') or {}).get('p50')
        lines.append(f'|{r["episode"]} / {r["arm"]} / {r["round"]}|{d["coverage_ge1"]*100:.2f}%|{d["coverage_ge5"]*100:.2f}%|{d["coverage_original_target"]*100:.2f}%|{median}|{d["area_below_half_original_stack"]*100:.2f}%|')
    lines += ['','## 结论边界','',
        '成功软件测试、候选预演和盒体分阶段集成不能证明汽车网格改善。basic Failed=0 也不能覆盖原生拓扑警告。拒绝的高覆盖网格不进入可行 Pareto 集。',
        '“明显改善”需在合格基线上 ≥5 层面积增加至少10个百分点、单元增长≤20%，≥1层与三个困难区域均不得下降超过2个百分点。基线不合格时单独判断是否修复成合格候选，不计算伪造覆盖增益。','']
    for c in comparisons:lines.append(f'- {c["baseline"]}：明显合格增益={c["clear_qualified_gain"]}；不合格直出修复成合格={c["repaired_invalid_baseline"]}。')
    for s,cost in sources.items():lines.append(f'- 源 SHA256 `{s}`：本轮全部版本 API 上界 ${cost:.6f}，上限 $0.50。')
    lines += ['','## 停止原因','']
    for r in runs:lines.append(f'- {r["episode"]} / {r["arm"]}：{r["stop_reason"]}。')
    lines += ['','用户指定的基座为 deepseek-flash。被中断的 Pro 实验单独保留，不进入 Flash 收益判断；已知费用与未知调用保留额仍计入同一原案例预算，未重置或转移。','']
    lines += ['','## 被排除的输入','']
    for r in excluded:lines.append(f'- {Path(r["source"]).name} / {r["preparation"]}：{r["error"] or r["native"]}。保留为输入审计失败，未作网格成功。')
    out.mkdir(parents=True,exist_ok=True);write_json(out/'study.json',result)
    (out/'NATIVE_RESULTS.zh-CN.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('out');a=p.parse_args()
    result=report_study(Path(a.root).resolve(),Path(a.out).resolve())
    print('terminal episodes',len(result['runs']),'new native stages',len(result['attempts']))
