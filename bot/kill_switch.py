"""Local operator-only reset for the persistent kill switch; never places orders."""
import argparse
from .config import from_env
from .storage import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset',action='store_true',required=True)
    args=parser.parse_args()
    settings=from_env()
    if settings.trading_mode!='DRY_RUN' or settings.trading_enabled:
        parser.error('Reset requires TRADING_MODE=DRY_RUN and TRADING_ENABLED=false')
    store=Store(settings.db_path)
    try:
        store.reset_kill_switch_local()
        print('Persistent kill switch reset locally. Trading remains disabled by environment.')
    finally:store.close()


if __name__=='__main__':main()
