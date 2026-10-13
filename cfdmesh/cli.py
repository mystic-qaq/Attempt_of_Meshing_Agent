from __future__ import annotations
import argparse
from pathlib import Path
from .io import read_json,write_json


def main():
    p=argparse.ArgumentParser(description='Evidence-gated whole-body external-flow meshing')
    sub=p.add_subparsers(dest='command',required=True)
    agent=sub.add_parser('agent')
    agent.add_argument('geometry');agent.add_argument('run_dir')
    agent.add_argument('--of-root',default=str(Path.home()/'.conda-envs/openfoam2412'))
    agent.add_argument('--budget',type=int,default=2_000_000)
    agent.add_argument('--max-rounds',type=int,default=5)
    agent.add_argument('--n-procs',type=int,default=1)
    agent.add_argument('--advisor',choices=['none','deepseek-flash'],default='none')
    agent.add_argument('--scale-to-metres',type=float,default=1)
    agent.add_argument('--centre-geometry',action='store_true',help='whole-body bbox-centre translation with recorded inverse; preserves source and source-hash monetary scope')
    agent.add_argument('--round-seconds',type=int,default=900)
    agent.add_argument('--total-seconds',type=int,default=3600)
    agent.add_argument('--speed',type=float,default=30)
    agent.add_argument('--nu',type=float,default=1.5e-5)
    agent.add_argument('--yplus',type=float,default=50)
    agent.add_argument('--layers',type=int,default=8)
    agent.add_argument('--base-cells',type=int,default=8)
    agent.add_argument('--no-layers',action='store_true',help='diagnostic mesh-only run; does not assert RANS readiness')
    agent.add_argument('--spec',help='optional explicit initial spec, still certified')
    agent.add_argument('--flow-probe',action='store_true',help='feed short numerical/actual-y+ probe failures into remaining mesh rounds')
    agent.add_argument('--model-plan',action='store_true',help='allow scientific tool dialogue before the first mesh')
    agent.add_argument('--probe-startup',type=int,default=0,help='optional 1..200 upwind startup steps, followed by 100 linearUpwind steps')
    agent.add_argument('--resume-from',help='resume immutable measured parent in a fresh root; combined attempts must remain <=5')
    agent.add_argument('--scenario',help='immutable physical scene JSON; +X flow, +Z up; unsupported environments rejected')
    serve=sub.add_parser('serve-advisor')
    serve.add_argument('run_dir');serve.add_argument('--key-file',required=True)
    serve.add_argument('--max-calls',type=int,default=24);serve.add_argument('--usd-limit',type=float,default=.5)
    serve.add_argument('--case-usd-limit',type=float,default=.5,help='shared ceiling across sibling runs of the same source geometry')
    serve.add_argument('--seconds',type=int,default=5400)
    serve.add_argument('--max-turns',type=int,default=4)
    serve.add_argument('--query-turns',type=int,help='adaptive measurement turns, leaving three turns for commitment/repair/review')
    serve.add_argument('--max-output',type=int,default=32768)
    serve.add_argument('--reasoning-effort',choices=['low','high','max'],default='high')
    serve.add_argument('--model',choices=['deepseek-flash','deepseek-v4-pro'],default='deepseek-flash')
    serve.add_argument('--review-policy',choices=['llm','program'],default='llm',help='program retains certified preview and native gates, omitting a second paid LLM review')
    test=sub.add_parser('selfcheck')
    smoke=sub.add_parser('solver-smoke')
    smoke.add_argument('run_dir')
    smoke.add_argument('--of-root',default=str(Path.home()/'.conda-envs/openfoam2412'))
    smoke.add_argument('--n-procs',type=int,default=8)
    smoke.add_argument('--iterations',type=int,default=30)
    smoke.add_argument('--seconds',type=int,default=600)
    args=p.parse_args()
    if args.command=='agent':
        from .agent import run_agent
        run=run_agent(args.geometry,args.run_dir,args.of_root,budget=args.budget,
            max_rounds=args.max_rounds,n_procs=args.n_procs,advisor=args.advisor,
            scale=args.scale_to_metres,round_seconds=args.round_seconds,total_seconds=args.total_seconds,centre_geometry=args.centre_geometry,
            require_layers=not args.no_layers,base_cells=args.base_cells,
            flow=dict(speed=args.speed,nu=args.nu,yplus=args.yplus,layers=args.layers),
            initial_override=read_json(args.spec) if args.spec else None,flow_probe=args.flow_probe,model_plan=args.model_plan,probe_startup=args.probe_startup,resume_from=args.resume_from,scenario_context=read_json(args.scenario) if args.scenario else None)
        print(run['status'],run.get('stop_reason'),flush=True)
        return 0 if run['accepted'] else 1
    if args.command=='serve-advisor':
        from .scientific_advisor import serve
        usage=serve(args.run_dir,args.key_file,max_calls=args.max_calls,cost_limit=args.usd_limit,seconds=args.seconds,case_cost_limit=args.case_usd_limit,max_turns=args.max_turns,max_output=args.max_output,reasoning_effort=args.reasoning_effort,query_turns=args.query_turns,review_policy=args.review_policy,model=args.model)
        print('advisor finished; calls:',usage['calls'],'estimated_usd:',usage['estimated_usd'])
        return 0
    if args.command=='solver-smoke':
        from .physics import solver_smoke
        report=solver_smoke(args.run_dir,args.of_root,args.n_procs,args.iterations,args.seconds)
        print(report['status'],report.get('iterations_completed'),report.get('error'))
        return 0 if report['accepted_for_smoke'] else 1
    import unittest
    test_root=Path(__file__).resolve().parents[1]/'tests'
    if not test_root.is_dir():
        p.error('selfcheck requires the source checkout with tests; run unittest from the repository')
    tests=unittest.defaultTestLoader.discover(str(test_root))
    return 0 if unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
