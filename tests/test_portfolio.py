"""The showcase must not select a rejected high-coverage mesh or hide an empty test run."""
import importlib.util
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

script=Path(__file__).resolve().parents[1]/'scripts/portfolio_report.py'
spec=importlib.util.spec_from_file_location('portfolio_report', script)
report=importlib.util.module_from_spec(spec); spec.loader.exec_module(report)
setup_spec=importlib.util.spec_from_file_location('portfolio_setup',script.with_name('portfolio_setup.py'))
setup_module=importlib.util.module_from_spec(setup_spec);setup_spec.loader.exec_module(setup_module)


class PortfolioReporting(unittest.TestCase):
    def test_previous_version_sees_new_expenses(self):
        from cfdmesh.io import write_json, read_json
        from cfdmesh.scientific_advisor import geometry_spend
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/'old';new=root/'new'
            (old/'runs/parent').mkdir(parents=True);(new/'runs/child').mkdir(parents=True)
            write_json(old/'api_budget_scope.json',dict(run_roots=[str(old/'runs')],lock_directory=str(root/'locks')))
            setup_module.sync_budget_scope(new,old)
            for run in (old/'runs/parent',new/'runs/child'):
                write_json(run/'manifest.json',dict(source_sha256='same-source'))
            write_json(new/'runs/child/advisor/usage.json',dict(estimated_usd=.12))
            self.assertEqual(geometry_spend(old/'runs/parent')[1],.12)
            self.assertEqual(read_json(old/'api_budget_scope.json')['lock_directory'],str(root/'locks'))

    def test_rejected_high_coverage_cannot_win(self):
        candidates=[dict(admissible_diagnostic=False,layer_coverage=.99,cells=200_000),
                    dict(admissible_diagnostic=True,layer_coverage=.80,cells=100_000),
                    dict(admissible_diagnostic=True,layer_coverage=.80,cells=90_000)]
        self.assertIs(report.select_attempt(candidates), candidates[2])
        self.assertIsNone(report.select_attempt(candidates[:1]))

    def test_installed_selfcheck_does_not_pass_zero_tests(self):
        from cfdmesh import cli
        with patch.object(cli, '__file__', '/missing/site-packages/cfdmesh/cli.py'), patch('sys.argv', ['cfdmesh','selfcheck']):
            with self.assertRaises(SystemExit) as caught: cli.main()
        self.assertEqual(caught.exception.code, 2)
