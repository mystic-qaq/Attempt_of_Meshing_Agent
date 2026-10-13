import unittest
from cfdmesh.cross_case import portable_actions,retrieve,promotion_check,descriptor


class ExperienceTest(unittest.TestCase):
    def test_no_coordinates_or_case_specific_cluster_ids_transfer(self):
        actions=[dict(kind='cluster_refine',ids=['old-face:5'],level=8,padding_cells=1,evidence=['old-face:5']),dict(kind='local_refine',min=[1,2,3],max=[4,5,6],level=7)]
        view=portable_actions(actions,5)
        self.assertEqual(view[0]['relative_surface_level'],3)
        self.assertNotIn('ids',view[0]);self.assertNotIn('min',view[1]);self.assertNotIn('evidence',view[0])

    def test_retrieval_excludes_same_original_and_unapproved_heldout_cases(self):
        g=dict(extents=[4.5,1.8,1.4],feature_half_size={'p5':.01},finite_fluid_gap_fraction=.3)
        p={'first_layer_height':.0013};desc=descriptor(g,p)
        facts=[dict(source_group_sha256=s,stage='snap',geometry_route='wrapped',descriptor=desc,research_eligible=False) for s in ('current-original','training','heldout')]
        found=retrieve(facts,g,p,'current-original','snap','wrapped',allowed_training_groups={'training'})
        self.assertEqual([r['source_group_sha256'] for r in found],['training'])
        self.assertFalse(found[0]['research_eligible'])  # Negative observations stay negative.

    def test_failed_high_coverage_and_derived_clone_cannot_promote_policy(self):
        good=dict(baseline_research_eligible=True,candidate_research_eligible=True,clear_gain=True,same_budget=True)
        train=[dict(good,source_group_sha256=s) for s in ('a','b')]
        self.assertTrue(promotion_check(train,[dict(good,source_group_sha256='c')])['promoted'])
        self.assertFalse(promotion_check(train,[dict(good,source_group_sha256='a')])['promoted'])
        bad=[dict(good,source_group_sha256='c',candidate_research_eligible=False)]
        self.assertFalse(promotion_check(train,bad)['promoted'])


if __name__=='__main__':unittest.main()
