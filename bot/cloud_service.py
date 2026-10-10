"""Guarded service entry points for the private Oracle DRY_RUN deployment."""
import argparse
import os

from .cloud import cloud_settings, scheduler_lease
from .simulation import initialize
from .storage import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service',choices=('dashboard','telegram'))
    args=parser.parse_args();cfg=cloud_settings()
    store=Store(cfg.db_path)
    try:
        initialize(store,cfg)
        if args.service=='dashboard':
            from waitress import serve
            from .web import create_app
            serve(create_app(cfg),listen='127.0.0.1:8765',threads=4)
        else:
            if os.getenv('TELEGRAM_ALLOWED_USER_ID')!='5561255226':
                raise ValueError('Authorized Telegram user configuration required')
            from .telegram.__main__ import main as telegram_main
            with scheduler_lease(str(cfg.db_path)+'.telegram'):telegram_main()
    finally:store.close()


if __name__=='__main__':main()
