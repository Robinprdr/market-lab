"""Run the private Telegram command/notification worker."""
import os
import sys
import time

from bot.config import from_env
from bot.storage import Store
from .client import BotAPI,TelegramWorker


def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    user=os.getenv('TELEGRAM_ALLOWED_USER_ID','').strip()
    if not token or not user.isdecimal():
        raise SystemExit('Set TELEGRAM_BOT_TOKEN and numeric TELEGRAM_ALLOWED_USER_ID privately')
    settings=from_env()
    store=Store(settings.db_path)
    worker=TelegramWorker(store,settings,BotAPI(token),int(user))
    try:
        while True:
            try:
                worker.flush_notifications()
                for update in worker.api.get_updates(store.telegram_offset()+1):
                    worker.process_update(update)
                    store.mark_telegram_update(update['update_id'])
            except KeyboardInterrupt:
                break
            except Exception:
                # Never print exception URLs: Bot API URLs include the token.
                print('Telegram polling/notification error; retrying',file=sys.stderr,flush=True)
                time.sleep(5)
    finally:store.close()


if __name__=='__main__':main()
