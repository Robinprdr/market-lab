"""Run the private Telegram command/notification worker."""
import os
import sys
import time

from bot.config import from_env
from bot.storage import Store
from .client import BotAPI,TelegramWorker,ResponseDeliveryError


def poll_once(worker):
    """Control commands take priority; notification delivery cannot starve /kill."""
    errors=0
    try:updates=worker.api.get_updates(worker.store.telegram_offset()+1)
    except Exception:updates=[];errors+=1
    for update in updates:
        try:worker.process_update(update)
        except ResponseDeliveryError:
            # /kill is durably applied before its reply. Do not let a failed
            # /status reply prevent a subsequent /kill in the same batch.
            errors+=1
        except Exception:
            errors+=1;break # No offset advance past an unapplied command.
        worker.store.mark_telegram_update(update['update_id'])
    try:worker.flush_notifications()
    except Exception:errors+=1
    return errors


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
                if poll_once(worker):
                    print('Telegram polling/notification error; retrying',file=sys.stderr,flush=True)
                    time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception:
                # Never print exception URLs: Bot API URLs include the token.
                print('Telegram polling/notification error; retrying',file=sys.stderr,flush=True)
                time.sleep(5)
    finally:store.close()


if __name__=='__main__':main()
