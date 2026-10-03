"""Private long-poll Telegram Bot API transport and concise message formatting."""
import json
from urllib import request

from bot.monitoring import dashboard_data


def money(value,signed=False):
    sign='+' if signed and value>=0 else ''
    return (sign+f'{value:,.2f}').replace(',',' ').replace('.',',')+' $'


def strategy_name(strategy_id):
    return 'Swing V2' if strategy_id=='2366a81673c5' else strategy_id


def event_message(kind,payload):
    if kind=='opened':
        return (f"LONG {payload['ticker']}\nEntrée : {money(payload['price'])}\n"
                f"Taille : {money(payload['notional_usd'])}\nStratégie : {strategy_name(payload['strategy'])}")
    if kind=='closed':
        pct=payload['pnl_pct']
        pct_text=f'{pct:+.2f}'.replace('.',',')
        return (f"{payload['ticker']} clôturé\nSortie : {money(payload['price'])}\n"
                f"P&L : {money(payload['pnl_usd'],True)} ({pct_text} %)")
    if kind=='daily':
        latent='indisponible' if payload.get('unrealized_pct') is None else f"{payload['unrealized_pct']:+.1f} %".replace('.',',')
        return (f"Market Lab — Résumé {payload['session']}\nPositions : {payload['positions']}\n"
                f"P&L latent : {latent}\nP&L réalisé du jour : {money(payload['realized_pnl_usd'],True)}\n"
                f"Erreurs critiques : {payload['critical_errors']}")
    if kind=='reconciliation':return 'Market Lab — Réconciliation bloquée. Vérifier le dashboard avant tout ordre.'
    if kind=='critical_error':return 'Market Lab — Erreur critique. Vérifier le dashboard.'
    if kind=='kill':return 'Market Lab — Kill switch activé. Aucun nouvel ordre.'
    raise ValueError('Unsupported notification kind')


class BotAPI:
    def __init__(self,token):
        if not token:raise ValueError('Telegram token required')
        self._token=token

    def _call(self,method,payload):
        url=f'https://api.telegram.org/bot{self._token}/{method}'
        body=json.dumps(payload).encode()
        req=request.Request(url,data=body,headers={'Content-Type':'application/json'})
        try:
            with request.urlopen(req,timeout=40) as response:
                result=json.load(response)
        except Exception:
            raise RuntimeError('Telegram API request failed') from None
        if not result.get('ok'):
            raise RuntimeError('Telegram API rejected request')
        return result['result']

    def send_message(self,chat_id,text):
        return self._call('sendMessage',{'chat_id':chat_id,'text':text})

    def get_updates(self,offset):
        return self._call('getUpdates',{'offset':offset,'timeout':30,'allowed_updates':['message']})


class TelegramWorker:
    def __init__(self,store,settings,api,allowed_user_id):
        self.store=store;self.settings=settings;self.api=api;self.allowed_user_id=int(allowed_user_id)

    def flush_notifications(self):
        sent=0
        for event in self.store.pending_notifications():
            self.api.send_message(self.allowed_user_id,event_message(event['kind'],json.loads(event['payload_json'])))
            self.store.mark_notification_sent(event['event_key'])
            sent+=1
        return sent

    def process_update(self,update):
        message=update.get('message') or {}
        sender=message.get('from') or {}
        chat=message.get('chat') or {}
        if (sender.get('id')!=self.allowed_user_id or chat.get('id')!=self.allowed_user_id
                or chat.get('type')!='private'):
            return False
        command=(message.get('text') or '').split(maxsplit=1)[0].split('@')[0]
        if command=='/status':
            view=dashboard_data(self.store,self.settings)
            critical=sum(e['code'] in ('RECONCILIATION_REQUIRED','RUN_FAILED','DATA_ERROR') for e in view['errors'])
            answer=(f"Market Lab — {view['state']}\nMode : {view['mode']}\n"
                    f"Broker : {'connecté' if view['broker_connected'] else 'non connecté'}\n"
                    f"Réconciliation : {view['reconciliation']}\nPositions : {view['position_count']}\n"
                    f"Erreurs critiques : {critical}\nKill switch : {'actif' if view['kill_switch_enabled'] else 'inactif'}")
        elif command=='/positions':
            positions=self.store.db.execute('SELECT * FROM positions ORDER BY ticker').fetchall()
            answer='Aucune position exécutée.' if not positions else '\n\n'.join(
                f"{p['ticker']} · {p['quantity']} titres\nPrix moyen : {money(p['avg_entry_price'])}\n"
                f"P&L latent : indisponible\nStratégie : {strategy_name(p['strategy_id'])}" for p in positions)
        elif command=='/kill':
            changed=self.store.activate_kill_switch('telegram')
            answer=('Kill switch activé. Aucun nouvel ordre. Les positions restent ouvertes.' if changed
                    else 'Kill switch déjà actif. Aucun nouvel ordre.')
        else:
            return False
        self.api.send_message(self.allowed_user_id,answer)
        return True
