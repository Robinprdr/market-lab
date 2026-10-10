"""Generate/install a per-user macOS launchd agent for DRY_RUN operations."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from .config import ROOT

LABEL='com.marketlab.operations.dryrun'


def agent_definition(python=sys.executable,root=ROOT):
    root=Path(root).resolve()
    return dict(Label=LABEL,ProgramArguments=[str(python),'-m','bot.operations','--interval','60'],
                WorkingDirectory=str(root),RunAtLoad=True,KeepAlive=True,ThrottleInterval=30,
                EnvironmentVariables={'TRADING_MODE':'DRY_RUN','TRADING_ENABLED':'false',
                                      'BOT_DB_PATH':str(root/'data/cache/bot_core/market_lab.sqlite')},
                StandardOutPath=str(root/'data/cache/bot_core/operations.stdout.log'),
                StandardErrorPath=str(root/'data/cache/bot_core/operations.stderr.log'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Write and start the user LaunchAgent')
    args=parser.parse_args()
    data=plistlib.dumps(agent_definition())
    if not args.install:
        sys.stdout.buffer.write(data)
        return
    clean_env={'PATH':os.environ.get('PATH','/usr/bin:/bin')}
    subprocess.run([sys.executable,'-c','import pandas, exchange_calendars, flask, bot.operations'],
                   cwd=ROOT,env=clean_env,check=True)
    path=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    path.parent.mkdir(parents=True,exist_ok=True)
    (ROOT/'data/cache/bot_core').mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    domain=f'gui/{os.getuid()}'
    subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
    print(path)


if __name__=='__main__':main()
