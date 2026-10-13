"""All-attempt reports; no rejected mesh can be selected for a coverage claim."""
import argparse
from pathlib import Path
from cfdmesh.io import read_json, write_json, sha256
from cfdmesh.scientific_advisor import geometry_spend
from cfdmesh.drivaer import clear_gain


def write_report(root,out,allow_running=False):
    protocol=read_json(root/'protocol.json');runs=[];lines=['# DrivAer 原生对照结果','',
        '自由空气单相网格研究；完整几何保留，首层物理高度固定。研究资格与工业 CFD 精度分开。','',
        '|案例 / 路线|状态|原生阶段|有效模型试验|合格研究候选|所选 ≥5 层面积|单元数|新增 API 费用上界|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    attempts=[]
    for entry in protocol['cases']:
        for arm in protocol['arms']:
            folder=root/'runs'/f'{entry["id"]}_{arm}';data=read_json(folder/'agent_run.json')
            if data['status']=='running' and not allow_running:raise ValueError('cannot publish an unfinished episode as final')
            _,shared,own=geometry_spend(folder);selected=data.get('selected');rows=data['rounds']
            item=dict(case=entry['id'],arm=arm,status=data['status'],rounds=len(rows),
                model_trials=sum(r['decision']['source']=='model' for r in rows),
                valid_layer_trials=sum(r['stage'] in ('layers','full') and r['research_eligible'] for r in rows),
                selected=selected,baseline=data.get('baseline'),clear_gain_vs_one_shot=data.get('clear_gain_vs_one_shot',False),
                own_usd_ceiling=own,shared_source_usd_ceiling=shared,stop_reason=data.get('stop_reason'),
                native_seconds=sum(r['native']['seconds'] for r in rows),
                measurement_seconds=sum(r['evidence']['measurement_seconds'] for r in rows),
                wall_seconds=data['seconds'],production_accepted=data.get('production_accepted',False),
                source_mutated=data['source_mutated'],code_sha256=data['code_sha256'])
            runs.append(item)
            coverage=f'{selected["coverage"]*100:.2f}%' if selected else '无'
            cells=f'{int(selected["cells"]):,}' if selected else '—'
            lines.append(f'|{entry["id"]} / {arm}|{data["status"]}|{len(rows)}|{item["model_trials"]}|{item["valid_layer_trials"]}|{coverage}|{cells}|${own:.6f}|')
            for row in rows:
                q=row['evidence'].get('quality') or {};metrics=q.get('metrics',{})
                attempts.append(dict(case_id=entry['id'],arm=arm,round=row['round'],attempt=row['round']+1,
                    stage=row['stage'],case=row['native']['case'],cells=metrics.get('cells'),
                    coverage_ge5=row['evidence']['layers'].get('coverage'),
                    admissible_diagnostic=row['research_eligible'],metrics=metrics,
                    native_failed=q.get('n_failed'),fidelity_accepted=row['evidence']['fidelity']['accepted'],
                    regional_layers=row['regional_layers'],layer_design=row.get('layer_design'),decision_source=row['decision']['source'],
                    actions=row['decision'].get('executed_actions'),model_plan=row['decision'].get('advisor'),
                    rejection_or_unavailable=(row['decision'].get('receipt') or {}).get('error'),
                    reasons=row['evidence']['reasons'],native_error=row['native'].get('error')))
    comparisons=[]
    for entry in protocol['cases']:
        llm=next((r for r in runs if r['case']==entry['id'] and r['arm']=='llm'),None)
        control=next((r for r in runs if r['case']==entry['id'] and r['arm']=='deterministic'),None)
        if not llm or not control:continue
        teacher=llm['selected'];program=control['selected']
        ref=dict(program or {},research_eligible=bool(program))
        stronger=clear_gain(teacher,ref) if teacher and program else False
        comparisons.append(dict(case=entry['id'],clear_gain_vs_program_feedback=stronger,
            valid_teacher_only=bool(teacher and not program),teacher_has_no_valid_candidate=not bool(teacher),
            gain_pp_vs_feedback=100*(teacher['coverage']-program['coverage']) if teacher and program else None,
            cells_ratio_vs_feedback=teacher['cells']/program['cells'] if teacher and program else None))
    lines+=['','## 全部阶段，包括失败','','|案例 / 路线|阶段|类型|动作来源|单元数|≥5 层面积|basic Failed|研究资格|',
            '|---|---:|---|---|---:|---:|---:|---|']
    for row in attempts:
        cov=f'{row["coverage_ge5"]*100:.2f}%' if row['coverage_ge5'] is not None else '—'
        cells=f'{int(row["cells"]):,}' if row['cells'] is not None else '—'
        lines.append(f'|{row["case_id"]} / {row["arm"]}|{row["attempt"]}|{row["stage"]}|{row["decision_source"]}|{cells}|{cov}|{row["native_failed"]}|{row["admissible_diagnostic"]}|')
    lines+=['','## 判断与限制','',
        '“明显改善”预先定义为 ≥5 层面积增加至少 10 个百分点、单元增长最多20%，≥1层与三个困难区域不得下降超过2个百分点。每个源几何在本轮研究中的API费用上限$0.50，重试共用。上界不是逐笔账单。','',
        '程序化直出未合格时，不能计算“相对合格基线的覆盖增益”。模型修复成合格候选与高覆盖但仍然失败的网格分别报告。取得合格网格不代表阻力或真实y+精度通过。','']
    for comparison in comparisons:lines.append(f'- {comparison["case"]}：明显优于同预算程序反馈={comparison["clear_gain_vs_program_feedback"]}；只有模型得到合格候选={comparison["valid_teacher_only"]}；覆盖差={comparison["gain_pp_vs_feedback"]}个百分点。')
    for run in runs:lines+=['',f'### {run["case"]} / {run["arm"]}',f'停止原因：{run["stop_reason"]}。原生阶段耗时 {run["native_seconds"]:.1f}s，独立测量 {run["measurement_seconds"]:.1f}s；完整墙钟时间 {run["wall_seconds"]:.1f}s。']
    lines+=['','## 输入排除','']
    for excluded in protocol.get('excluded_inputs',[]):lines.append(f'- {excluded["id"]}：{excluded.get("error") or excluded.get("exclusion") or excluded.get("native",{}).get("reasons")}。排除记录保留，不属于网格成功。')
    out.mkdir(parents=True,exist_ok=True)
    summary=dict(protocol_sha256=sha256(root/'protocol.json'),runs=runs,comparisons=comparisons,attempts=attempts,
        status='partial' if any(r['status']=='running' for r in runs) else 'complete',physical_accuracy='unverified')
    write_json(out/'comparison.json',summary)
    (out/'REPORT.zh-CN.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('experiment');p.add_argument('output');p.add_argument('--allow-running',action='store_true')
    a=p.parse_args();summary=write_report(Path(a.experiment),Path(a.output),a.allow_running)
    print(summary['status'],[(r['case'],r['arm'],r['valid_layer_trials']) for r in summary['runs']])
