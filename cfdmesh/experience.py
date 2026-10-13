"""Bounded evidence catalogue; observations are not automatically promoted to rules."""
from .io import write_json


def observations(run,output):
    records=[]
    for previous,current in zip(run['rounds'],run['rounds'][1:]):
        before,after=previous['evidence'],current['evidence']
        records.append(dict(source_geometry_sha256=run['source_sha256'],
                scenario_contract_sha256=(run.get('scenario') or {}).get('contract_sha256'),
                physical_family=(run.get('scenario') or {}).get('context',{}).get('family'),
                scenario_screen_before=before.get('scenario_screen'),scenario_screen_after=after.get('scenario_screen'),
                from_round=previous['round'],to_round=current['round'],
                hypothesis=current['decision'],before_reasons=before['reasons'],
                after_reasons=after['reasons'],accepted_after=current['accepted'],
                native_checks_before=(before.get('quality') or {}).get('n_failed'),
                native_checks_after=(after.get('quality') or {}).get('n_failed'),
                status='candidate_observation',generalisation='unproven',
                promotion_requires=['independent geometry families','held-out case',
                                    'counterexample search','regression test','bounded rule implementation']))
    write_json(output,dict(observations=records[:5],automatic_rule_promotion=False,
                           prompt_growth_policy='fixed schemas; at most five-round local history'))
