"""Explicit real Telegram test; never instantiates or connects to a broker."""
import argparse
import os
import re
from pathlib import Path
import tempfile

from .config import from_env
from .storage import Store
from .telegram.client import BotAPI,TelegramWorker

ALLOWED_USER_ID=5561255226
SMOKE_MESSAGE='Market Lab — Test Telegram\nConnexion réussie.\nMode : DRY_RUN\nTrading : désactivé'


def credentials():
    token=os.environ.get('TELEGRAM_BOT_TOKEN','').strip()
    if not token:raise ValueError('TELEGRAM_BOT_TOKEN absent')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{30,}',token):
        raise ValueError('TELEGRAM_BOT_TOKEN format invalid')
    if os.environ.get('TELEGRAM_ALLOWED_USER_ID','')!=str(ALLOWED_USER_ID):
        raise ValueError('TELEGRAM_ALLOWED_USER_ID must be 5561255226 for this test')
    return token,ALLOWED_USER_ID


def smoke(api,user_id):
    if user_id!=ALLOWED_USER_ID:raise ValueError('Unauthorized smoke test recipient')
    identity=api.get_me()
    if not identity.get('is_bot') or not identity.get('username'):
        raise RuntimeError('Invalid bot identity')
    result=api.send_message(user_id,SMOKE_MESSAGE)
    if result.get('chat',{}).get('id')!=user_id or not result.get('message_id'):
        raise RuntimeError('Message not acknowledged for authorized chat')
    return identity['username']


def test_alerts(api,user_id):
    """Synthetic events in a disposable ledger, clearly marked TEST on delivery."""
    class TestAPI:
        def send_message(self,chat_id,text):
            return api.send_message(chat_id,'[TEST — aucun trade exécuté]\n'+text)
    events=[
        ('opened',dict(ticker='NVDA',price=184.20,notional_usd=1000.,strategy='2366a81673c5')),
        ('closed',dict(ticker='NVDA',price=191.80,pnl_usd=41.26,pnl_pct=4.13)),
        ('daily',dict(session='TEST',positions=0,realized_pnl_usd=0.,critical_errors=0)),
        ('critical_error',{}),('reconciliation',{})]
    with tempfile.TemporaryDirectory(prefix='market-lab-telegram-alerts-') as directory:
        store=Store(Path(directory)/'test.sqlite')
        try:
            with store.tx() as db:
                for index,(kind,payload) in enumerate(events):
                    store._enqueue(db,f'test:{index}',kind,payload)
            worker=TelegramWorker(store,from_env(),TestAPI(),user_id)
            return worker.flush_notifications()
        finally:store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-alerts',action='store_true',help='Also send five explicitly synthetic alerts')
    args=parser.parse_args()
    try:
        settings=from_env()
        if settings.trading_mode!='DRY_RUN' or settings.trading_enabled:
            raise ValueError('Requires TRADING_MODE=DRY_RUN and TRADING_ENABLED=false')
        token,user_id=credentials()
        api=BotAPI(token)
        username=smoke(api,user_id)
        print(f'getMe: PASS — @{username}; sendMessage: PASS — authorized chat acknowledged',flush=True)
        if args.test_alerts:print(f'TEST alerts acknowledged: {test_alerts(api,user_id)}',flush=True)
    except Exception:
        raise SystemExit('Telegram smoke test FAIL. Check private environment and bot chat; no secret logged.') from None


if __name__=='__main__':main()
