"""Build an immutable cross-case experience snapshot from terminal native runs."""
import argparse
from cfdmesh.cross_case import collect,write_store,full_baseline_facts

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--experiment',action='append',default=[])
    p.add_argument('--full-baseline',action='append',default=[])
    a=p.parse_args();facts=collect(a.experiment)+full_baseline_facts(a.full_baseline);write_store(a.output,facts)
    print('native facts',len(facts),'positive generalized rules',0)
