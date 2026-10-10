"""Export only the deployment's code, frozen inputs and configuration; no caches/secrets."""
import argparse
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[2]


def members():
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    # Also include not-yet-committed deployment source during local preparation.
    files=set(tracked)|{str(p.relative_to(ROOT)) for p in (ROOT/'bot').rglob('*') if p.is_file()}
    exact={'research/__init__.py','research/v2_2026/__init__.py','research/v2_2026/download_daily.py',
           'results/research_v2/frozen_candidates.json','results/research_v2/frozen_candidates.json.sha256',
           'data/universe/top100_us_v1.csv','requirements-bot.txt','requirements-cloud.txt',
           'bot/deploy/constraints.txt','results/oracle_deployment/local_validation.json'}
    files|=exact
    chosen=[]
    for name in sorted(files):
        p=Path(name)
        if not name or '__pycache__' in p.parts:continue
        if name in exact or name.startswith('research/research_v2/') and p.suffix in ('.py','.json','.txt') or name.startswith('bot/') and (p.suffix in ('.py','.md','.html','.sh','.service','.timer','.conf','.example') or name=='bot/deploy/start-gateway'):
            if (ROOT/name).is_file():chosen.append(name)
    return chosen


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    with tarfile.open(args.output,'x:gz') as archive:
        for name in members():archive.add(ROOT/name,arcname='market-lab/'+name,recursive=False)
    print('Deployment bundle created; no market-data caches or credentials')


if __name__=='__main__':main()
