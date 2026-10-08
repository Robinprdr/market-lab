"""Reproducible entrypoint. Existing exploration freezes are never retuned."""
import argparse
import sys
from .common import OUT

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['all','download','audit','features','exploration','validation','final'],default='all');p.add_argument('--workers',type=int,default=4);args=p.parse_args()
    stages=['download','audit','features','exploration','validation','final'] if args.stage=='all' else [args.stage]
    for stage in stages:
        print('STAGE',stage,flush=True)
        if stage=='download':
            from . import download
            sys.argv=['download','--workers',str(args.workers)];download.main()
        elif stage=='audit':
            from . import audit_cache
            audit_cache.main()
        elif stage=='features':
            from . import features
            sys.argv=['features'];features.main()
        elif stage=='exploration':
            from . import search
            if (OUT/'frozen_intraday_candidates.json').exists():search.verify_frozen();print('Existing freeze verified; exploration skipped')
            else:search.main()
        else:
            from . import validate
            sys.argv=['validate',stage];validate.main()

if __name__=='__main__':main()
