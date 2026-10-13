"""Budget continuity, feasible candidate selection, and nonempty software checks."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from cfdmesh.budget_scope import sync_budget_scope
from cfdmesh.io import write_json, read_json
from cfdmesh.scientific_advisor import geometry_spend
from cfdmesh.drivaer import update_archive


class Reporting(unittest.TestCase):
    def test_parent_scope_sees_new_expenses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/'old';new=root/'new'
            (old/'runs/parent').mkdir(parents=True);(new/'runs/child').mkdir(parents=True)
            write_json(old/'api_budget_scope.json',dict(run_roots=[str(old/'runs')],lock_directory=str(root/'locks')))
            sync_budget_scope(new,old)
            for run in (old/'runs/parent',new/'runs/child'):
                write_json(run/'manifest.json',dict(source_sha256='same-source'))
            write_json(new/'runs/child/advisor/usage.json',dict(estimated_usd=.12))
            self.assertEqual(geometry_spend(old/'runs/parent')[1],.12)
            self.assertEqual(read_json(old/'api_budget_scope.json')['lock_directory'],str(root/'locks'))

    def test_rejected_high_coverage_cannot_enter_archive(self):
        def record(eligible, coverage, cells, index):
            return dict(research_eligible=eligible,stage='full',round=index,spec={},
                native={'case':str(index)},regional_layers={},evidence=dict(
                layers={'coverage':coverage,'area_fraction_by_layers':{'0':0}},
                quality={'metrics':{'cells':cells}}))
        archive=update_archive([],record(False,.99,200000,0))
        self.assertEqual(archive,[])
        archive=update_archive(archive,record(True,.80,100000,1))
        archive=update_archive(archive,record(True,.80,90000,2))
        self.assertEqual([r['round'] for r in archive],[2])

    def test_installed_selfcheck_does_not_pass_zero_tests(self):
        from cfdmesh import cli
        with patch.object(cli,'__file__','/missing/site-packages/cfdmesh/cli.py'),patch('sys.argv',['cfdmesh','selfcheck']):
            with self.assertRaises(SystemExit) as caught: cli.main()
        self.assertEqual(caught.exception.code,2)

    def test_figures_select_current_route_and_retain_rejected_trials(self):
        from scripts.drivaer_visualize import select_attempts
        rejected=dict(case_id='drivaer_410',arm='llm',round=1,admissible_diagnostic=False)
        other=dict(case_id='drivaer_318',arm='llm',round=1,admissible_diagnostic=True)
        report={'attempts':[rejected,other]}
        self.assertEqual(select_attempts(report,'drivaer_410','llm',1),[rejected])
        self.assertEqual(select_attempts(report,'drivaer_410','deterministic',1),[])
