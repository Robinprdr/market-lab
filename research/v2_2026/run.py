"""One locked 2026 check; never searches or changes the frozen V2 candidate."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.research_v2.features import daily_features
from research.research_v2.run import load_frozen
from research.research_v2.search import Lab, rule_mask

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
OUT = ROOT/'results/research_v2_2026'
PRICE = ROOT/'data/cache/v2_2026_check/ohlcv.csv'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locked_inputs():
    cfg = json.loads((HERE/'protocol.json').read_text())
    frozen = load_frozen(ROOT/'results/research_v2/frozen_candidates.json')
    candidate, = [x for x in frozen['candidates'] if x['id'] == cfg['candidate_id']]
    protocol = json.loads((ROOT/'research/research_v2/protocol.json').read_text())
    if candidate['lab'] != 'swing' or candidate['horizon'] != 9:
        raise ValueError('Unexpected frozen candidate')
    if sha(ROOT/'data/universe/top100_us_v1.csv') != frozen['universe_sha256']:
        raise ValueError('Frozen universe changed')
    return cfg, candidate, protocol['swing']['round_trip_cost']


def check_prices(raw, cfg):
    universe = set(pd.read_csv(ROOT/'data/universe/top100_us_v1.csv').ticker)
    if set(raw.Ticker) != universe | {'SPY'}:
        raise ValueError('Universe mismatch or missing ticker')
    if raw.duplicated(['Ticker','Date']).any():
        raise ValueError('Duplicate daily prices')
    if raw[['Open','High','Low','Close','Volume']].isna().any().any():
        raise ValueError('Missing OHLCV')
    if (raw[['Open','High','Low','Close']] <= 0).any().any():
        raise ValueError('Nonpositive OHLC')
    if (raw.High + 1e-6 < raw[['Open','Close','Low']].max(axis=1)).any() or (raw.Low - 1e-6 > raw[['Open','Close','High']].min(axis=1)).any():
        raise ValueError('Invalid OHLC')
    calendar = pd.DatetimeIndex(sorted(raw[raw.Ticker.eq('SPY')].Date.unique()))
    if calendar.min() > pd.Timestamp(cfg['daily_warmup_start']) + pd.Timedelta(days=4) or calendar.max() != pd.Timestamp(cfg['last_complete_session']):
        raise ValueError('Incomplete SPY period')
    for ticker, f in raw.groupby('Ticker'):
        expected = calendar[(calendar >= f.Date.min()) & (calendar <= calendar.max())]
        actual = pd.DatetimeIndex(f.Date)
        if len(expected.difference(actual)) or len(actual.difference(calendar)) or actual.max() != calendar.max():
            raise ValueError(f'{ticker}: incomplete sessions from first available date')
    return calendar


def prepare_lab(raw, cfg, h, cost):
    # Features see earlier dates, but Lab receives/evaluates 2026 only.
    features, _ = daily_features(raw)
    lab = Lab(features, 'swing', [cfg['start'], cfg['last_complete_session']], [h], cost)
    if lab.f.Date.min() < pd.Timestamp(cfg['start']):
        raise AssertionError('Pre-2026 row in evaluable frame')
    return lab


def selected_trades(lab, candidate):
    h = candidate['horizon']
    ix = lab.select(rule_mask(lab.f, candidate['rules']), h)
    trades, sleeve_dd = lab.details(ix, h)
    if len(trades):
        trades['Signal'] = pd.to_datetime(trades.Signal)
        trades['Entry'] = pd.to_datetime(trades.Entry)
        trades['Exit'] = pd.to_datetime(trades.Exit)
        if not (trades.Signal < trades.Entry).all() or not (trades.Entry <= trades.Exit).all():
            raise AssertionError('Bad signal/entry/exit alignment')
        if trades[['Signal','Entry','Exit']].min().min() < pd.Timestamp('2026-01-01'):
            raise AssertionError('Trade outside 2026')
    return trades, sleeve_dd


def stats(t):
    if t.empty:
        return {'trades': 0, 'win_rate': np.nan, 'average_gross': np.nan, 'average_net': np.nan,
                'median_net': np.nan, 'pf_net': np.nan, 'expectancy_net': np.nan}
    r = t.Net.astype(float)
    gain = r[r > 0].sum(); loss = -r[r < 0].sum()
    return {'trades': len(t), 'win_rate': r.gt(0).mean(), 'average_gross': t.Gross.mean(),
            'average_net': r.mean(), 'median_net': r.median(), 'pf_net': gain/loss if loss else np.inf,
            'expectancy_net': r.mean()}


def portfolio(raw, signals, calendar, cfg, cost, excluded=()):
    """2026 standardized 10k USD, 10% per entry, at most five concurrent positions.

    Matches V1 comparison convention: open first, close second, ticker order,
    no deferred orders. Round-trip cost is split equally on entry and exit,
    each half charged on original entry notional.
    """
    p = cfg['portfolio']; initial = float(p['initial_usd'])
    prices = {d:g.set_index('Ticker') for d,g in raw.groupby('Date')}
    orders = {d:g.sort_values('Ticker') for d,g in signals[~signals.Ticker.isin(excluded)].groupby('Entry')}
    cash = previous = initial; positions = {}; trades = []; curve = []
    for date in calendar[(calendar >= cfg['start']) & (calendar <= cfg['last_complete_session'])]:
        today = prices[date]
        budget = previous * p['weight_per_entry']
        for row in orders.get(date, pd.DataFrame()).itertuples(index=False):
            if row.Ticker in positions or len(positions) >= p['max_positions']:
                continue
            entry = float(today.loc[row.Ticker,'Open']); fee = budget * cost/2
            if cash < budget + fee:
                continue
            cash -= budget + fee
            positions[row.Ticker] = dict(Ticker=row.Ticker, Signal=row.Signal, Entry=date, Exit=row.Exit,
                Entry_Price=entry, Notional=budget, Qty=budget/entry)
        for ticker, pos in list(positions.items()):
            if pos['Exit'] == date:
                exit_price = float(today.loc[ticker,'Close'])
                gross = exit_price/pos['Entry_Price'] - 1
                net = gross - cost
                cash += pos['Qty']*exit_price - pos['Notional']*cost/2
                trades.append(dict(**pos, Exit_Price=exit_price, Gross=gross, Net=net,
                                   Gross_USD=pos['Notional']*gross, Net_USD=pos['Notional']*net))
                del positions[ticker]
        equity = cash + sum(pos['Qty']*float(today.loc[t,'Close']) for t,pos in positions.items())
        curve.append(dict(Date=date, Equity=equity, Open_Positions=len(positions)))
        previous = equity
        if cash < -1e-7 or len(positions) > p['max_positions']:
            raise AssertionError('Portfolio cash/position constraint')
    if positions:
        raise AssertionError('Unclosed portfolio position')
    accepted = pd.DataFrame(trades)
    if len(accepted) and not np.isclose(cash-initial,accepted.Net_USD.sum(),atol=1e-6):
        raise AssertionError('Portfolio reconciliation')
    curve = pd.DataFrame(curve)
    equity = pd.concat([pd.Series([initial]),curve.Equity],ignore_index=True)
    return accepted, curve, float(equity.iloc[-1]/initial-1), float((equity/equity.cummax()-1).min())


def verdict(s, portfolio_return, after):
    if s['trades'] >= 30 and s['average_net'] > 0 and s['pf_net'] >= 1.10 and portfolio_return > 0 and after['average_net'] > 0:
        return 'PASS'
    if s['average_net'] > 0 and s['pf_net'] > 1:
        return 'WEAK'
    return 'FAIL'


def main():
    cfg, candidate, cost = locked_inputs()
    raw = pd.read_csv(PRICE,parse_dates=['Date'])
    calendar = check_prices(raw,cfg)
    lab = prepare_lab(raw,cfg,candidate['horizon'],cost)
    trades,sleeve_dd = selected_trades(lab,candidate)
    s = stats(trades)
    concentration = (trades.groupby('Ticker',as_index=False).agg(trades=('Net','size'),gross_contribution=('Gross','sum'),
                     net_contribution=('Net','sum'),average_net=('Net','mean'))
                     .sort_values(['net_contribution','Ticker'],ascending=[False,True]))
    top5 = concentration.head(5).Ticker.tolist()
    without = trades[~trades.Ticker.isin(top5)]
    s5 = stats(without)
    portfolio_trades,curve,port_return,dd = portfolio(raw,trades,calendar,cfg,cost)
    _,_,port5,dd5 = portfolio(raw,trades,calendar,cfg,cost,top5)
    accepted = portfolio_trades.set_index(['Ticker','Signal']) if len(portfolio_trades) else pd.DataFrame()
    trades['Portfolio_Accepted'] = [((t,sig) in accepted.index) for t,sig in zip(trades.Ticker,trades.Signal)]
    trades['Portfolio_Net_USD'] = [float(accepted.loc[(t,sig),'Net_USD']) if (t,sig) in accepted.index else 0.
                                   for t,sig in zip(trades.Ticker,trades.Signal)]
    concentration['portfolio_net_usd'] = concentration.Ticker.map(portfolio_trades.groupby('Ticker').Net_USD.sum() if len(portfolio_trades) else {}).fillna(0.)
    concentration['removed_top5'] = concentration.Ticker.isin(top5)
    monthly = []
    previous = cfg['portfolio']['initial_usd']
    for month,group in curve.groupby(curve.Date.dt.to_period('M')):
        month_trades = trades[trades.Entry.dt.to_period('M').eq(month)]
        end = group.Equity.iloc[-1]
        monthly.append(dict(month=str(month),**stats(month_trades),portfolio_return=end/previous-1,
                            portfolio_end_equity=end,portfolio_accepted_trades=int(portfolio_trades.Entry.dt.to_period('M').eq(month).sum()) if len(portfolio_trades) else 0))
        previous=end
    decision = verdict(s,port_return,s5)
    top5_share = concentration.head(5).net_contribution.sum()/concentration.net_contribution.sum() if len(concentration) and concentration.net_contribution.sum() else np.nan
    OUT.mkdir(parents=True,exist_ok=True)
    pd.DataFrame([dict(scenario='full',**s,max_drawdown=dd,portfolio_return=port_return,portfolio_end_equity=curve.Equity.iloc[-1],
                       portfolio_accepted_trades=len(portfolio_trades),sleeve_drawdown=sleeve_dd),
                  dict(scenario='without_top5',**s5,max_drawdown=dd5,portfolio_return=port5,
                       portfolio_end_equity=cfg['portfolio']['initial_usd']*(1+port5),
                       portfolio_accepted_trades=np.nan,sleeve_drawdown=np.nan)]).to_csv(OUT/'summary.csv',index=False)
    pd.DataFrame(monthly).to_csv(OUT/'monthly.csv',index=False)
    concentration.to_csv(OUT/'ticker_contribution.csv',index=False)
    trades.to_csv(OUT/'trades.csv',index=False)
    manifest = json.loads((PRICE.parent/'manifest.json').read_text())
    text = [f'# V2 swing candidate — 2026 check: {decision}','',
            f"Candidate `{candidate['id']}` loaded from frozen file; horizon {candidate['horizon']} sessions; cost {cost:.2%} round trip.",
            f"Price source Yahoo adjusted OHLC; panel SHA256 `{sha(PRICE)}`; last complete session {cfg['last_complete_session']}.",
            f"Frozen candidate SHA256 `{sha(ROOT/'results/research_v2/frozen_candidates.json')}`. Frozen rules and V2 code were not edited.",
            f"Universe: fixed Top100 US V1, {len(manifest['tickers'])-1} stocks plus SPY. Earlier rows are feature warmup only.",
            f"Signal at close t, entry at next session Open, exit at close t+{candidate['horizon']}; trades crossing the data end are purged.",
            f"Trades {s['trades']}; win {s['win_rate']:.2%}; gross {s['average_gross']:.4%}; net/expectancy {s['average_net']:.4%}; median net {s['median_net']:.4%}; PF {s['pf_net']:.3f}.",
            f"Standardized portfolio: 10,000 USD initial, 10% equity per entry, max 5 positions, ticker order, no deferred orders; accepted {len(portfolio_trades)}; return {port_return:.4%}; maximum drawdown {dd:.4%}.",
            f"Five largest net-contribution tickers: {', '.join(top5)} ({top5_share:.2%} of aggregate signal net contribution). Without them: {s5['trades']} trades; average net {s5['average_net']:.4%}; PF {s5['pf_net']:.3f}; portfolio return {port5:.4%}.",
            f"Monthly factor average net is positive in {sum(x['average_net'] > 0 for x in monthly if pd.notna(x['average_net']))}/{sum(pd.notna(x['average_net']) for x in monthly)} active entry months; monthly detail is in monthly.csv.",
            '', '## Intraday data feasibility', '',
            'Alpaca credentials were absent in this environment, so no actual historical 1-minute feed or depth could be measured. The read-only six-ticker IEX/SIP audit and pagination/timezone tests are prepared; see alpaca_audit.json and research/v2_2026/README.md. Verdict: ALPACA_FREE_LIMITED pending a real Basic-account test. Alpaca documents live Basic IEX and historical SIP older than 15 minutes, but this account entitlement and multi-year completeness remain unverified. Massive Stocks Starter advertises five years of minute aggregates at US$29/month as a paid fallback.',
            '', 'The 2024–2025 validation had already been viewed in earlier research. The 2026 check uses the later fixed candidate but is still a retrospective backtest with revised daily data, idealized next-open/exit-close execution, and constant costs.',
            'The verdict follows the criteria fixed in research/v2_2026/protocol.json. No parameter was retuned.']
    (OUT/'decision.md').write_text('\n'.join(text)+'\n')
    print('\n'.join(text))


if __name__ == '__main__':
    main()
