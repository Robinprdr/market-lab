"""Local-only Flask monitor; all trading remains in Bot Core, never in HTTP routes."""
import argparse
from secrets import token_urlsafe

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from .config import from_env
from .monitoring import dashboard_data
from .storage import Store


def create_app(settings=None):
    settings=settings or from_env()
    if settings.trading_mode!='DRY_RUN' or settings.trading_enabled:
        raise ValueError('Operations web V1 is DRY_RUN only; PAPER activation is blocked')
    app=Flask(__name__)
    csrf=token_urlsafe(32)

    @app.get('/')
    def index():
        store=Store(settings.db_path)
        try:data=dashboard_data(store,settings)
        finally:store.close()
        return render_template('dashboard.html',data=data,csrf=csrf)

    @app.get('/api/state')
    def state():
        store=Store(settings.db_path)
        try:return jsonify(dashboard_data(store,settings))
        finally:store.close()

    @app.post('/control/dry-run')
    def control():
        if request.form.get('csrf')!=csrf:abort(403)
        origin=request.headers.get('Origin')
        if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):abort(403)
        value=request.form.get('enabled')
        if value not in ('0','1'):abort(400)
        store=Store(settings.db_path)
        try:
            if value=='1' and store.kill_switch_enabled():abort(409)
            store.set_dry_run_enabled(value=='1')
            store.set_operations_state('READY' if value=='1' else 'DISABLED')
        finally:store.close()
        return redirect(url_for('index'))

    return app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    app=create_app()
    app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False)


if __name__=='__main__':main()
