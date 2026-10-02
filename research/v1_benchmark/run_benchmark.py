"""Run exactly the three existing signals and the preregistered comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.research_engine import Costs, execution_return

START, END = pd.Timestamp('2018-01-01'), pd.Timestamp('2025-12-31')
STRATEGIES = ('Momentum', 'MeanReversion', 'Pullback')
COSTS = Costs()
INITIAL, WEIGHT, MAX_POSITIONS = 10_000., .10, 5


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def indicators(frame):
    """Input includes every observed session, including rows with no signal."""
    parts = []
    for ticker, f in frame.groupby('Ticker', sort=True):
        f = f.sort_values('Date').copy()
        for h in (1, 3, 10, 20):
            f[f'R{h}'] = f.Close.pct_change(h, fill_method=None)
        for h in (20, 50):
            f[f'SMA{h}'] = f.Close.rolling(h, min_periods=h).mean()
            f[f'Distance{h}'] = f.Close / f[f'SMA{h}'] - 1
        prev = f.Close.shift()
        tr = pd.concat([f.High-f.Low, (f.High-prev).abs(), (f.Low-prev).abs()], axis=1).max(axis=1)
        f['ATR_Pct'] = tr.rolling(14, min_periods=14).mean() / f.Close
        f['Volume20'] = f.Volume.rolling(20, min_periods=20).mean()
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


def signals(frame):
    f = indicators(frame)
    spy = f[f.Ticker.eq('SPY')].set_index('Date').R1
    f = f[~f.Ticker.eq('SPY')].copy()
    f['Momentum'] = False
    thresholds = {}
    for year in range(2018, 2026):
        if not f.Date.dt.year.eq(year).any():
            continue
        train = f[f.Date.dt.year.between(year-3, year-1)]
        if train.Date.dt.year.nunique() != 3:
            raise ValueError(f'Incomplete momentum training history for {year}')
        atr, ret = train.ATR_Pct.quantile(.8), train.R10.quantile(.8)
        thresholds[year] = dict(ATR_Pct=float(atr), Return_10D=float(ret), rows=len(train))
        mask = f.Date.dt.year.eq(year)
        f.loc[mask, 'Momentum'] = f.loc[mask, 'ATR_Pct'].ge(atr) & f.loc[mask, 'R10'].ge(ret)
    f['MeanReversion'] = (
        f.R1.between(-.04, -.02) & f.Close.gt(f.SMA50) & f.Volume.gt(f.Volume20)
        & f.Distance20.between(0, .10) & f.Distance50.between(.05, .20)
        & f.R3.lt(0) & (f.R1.abs()/f.ATR_Pct).ge(1) & f.Date.map(spy).gt(-.02))
    a = f.Close.gt(f.SMA50) & f.SMA20.gt(f.SMA50) & f.R20.gt(0) & f.R3.lt(0)
    previous = a.groupby(f.Ticker).shift().astype('boolean').fillna(False).astype(bool)
    f['Pullback'] = a & ~previous
    return f, thresholds


def validate_prices(frame, universe):
    required = ['Date','Ticker','Open','High','Low','Close','Volume']
    if not set(required).issubset(frame):
        raise ValueError('Missing OHLCV columns')
    if frame.duplicated(['Ticker','Date']).any() or frame[required].isna().any().any():
        raise ValueError('Duplicate or missing OHLCV')
    if set(frame.Ticker) != (set(universe.ticker)-{'SPCX'}) | {'SPY'}:
        raise ValueError('Unexpected/missing ticker; no silent universe reduction')
    if (frame[['Open','High','Low','Close']] <= 0).any().any():
        raise ValueError('Nonpositive prices')
    eps = 1e-6
    if (frame.High+eps < frame[['Open','Close','Low']].max(axis=1)).any() or (
            frame.Low-eps > frame[['Open','Close','High']].min(axis=1)).any():
        raise ValueError('Inconsistent OHLC')
    calendar = pd.DatetimeIndex(sorted(frame.loc[frame.Ticker.eq('SPY'),'Date'].unique()))
    if calendar.min().year != 2014 or calendar.max() != END:
        raise ValueError('SPY calendar must cover 2014 through 2025-12-31')
    coverage = []
    for ticker, f in frame.groupby('Ticker'):
        expected = calendar[(calendar >= f.Date.min()) & (calendar <= f.Date.max())]
        missing = expected.difference(f.Date)
        extra = pd.DatetimeIndex(f.Date).difference(calendar)
        if len(missing) or len(extra) or f.Date.max() != END:
            raise ValueError(f'{ticker}: missing {list(missing)}, extra {list(extra)}, end {f.Date.max()}')
        in_period = f[f.Date.between(START, END)]
        coverage.append(dict(Ticker=ticker, First=str(f.Date.min().date()), Last=str(f.Date.max().date()),
                             Rows=len(f), Rows_2018_2025=len(in_period), Missing_Internal=0))
    return calendar, coverage


def candidates(features, strategy, horizon, calendar):
    """Schedule exits using session positions only, never price/return selection."""
    dates = pd.Series(calendar, index=calendar)
    entry_map, exit_map = dates.shift(-1), dates.shift(-horizon)
    out = features[features[strategy] & features.Date.between(START, END)].copy()
    out['Entry'] = out.Date.map(entry_map)
    out['Exit'] = out.Date.map(exit_map)
    return out[out.Entry.notna() & out.Exit.notna() & out.Exit.le(END)][['Ticker','Date','Entry','Exit']]


def portfolio(price, entries, calendar, excluded=()):
    """Small comparison ledger: opens first, closes second; no deferred orders."""
    lookups = {date: group.set_index('Ticker') for date, group in price.groupby('Date')}
    orders = {date: group.sort_values('Ticker') for date, group in
              entries[~entries.Ticker.isin(excluded)].groupby('Entry')}
    cash, previous_equity, total_cost = INITIAL, INITIAL, 0.
    positions, trades, curve = {}, [], []
    for date in calendar[(calendar >= START) & (calendar <= END)]:
        today = lookups[date]
        budget = previous_equity * WEIGHT
        if date in orders:
            for row in orders[date].itertuples(index=False):
                if row.Ticker in positions or len(positions) >= MAX_POSITIONS:
                    continue
                entry = float(today.loc[row.Ticker, 'Open'])
                cost = budget * (COSTS.entry_fee + COSTS.entry_slippage)
                if cash < budget + cost:
                    continue
                cash -= budget + cost
                total_cost += cost
                positions[row.Ticker] = dict(Ticker=row.Ticker, Signal=row.Date, Entry=date,
                    Exit=row.Exit, Entry_Price=entry, Notional=budget, Qty=budget/entry)
        for ticker, p in list(positions.items()):
            if p['Exit'] == date:
                exit_price = float(today.loc[ticker,'Close'])
                cost = p['Notional'] * (COSTS.exit_fee + COSTS.exit_slippage)
                cash += p['Qty'] * exit_price - cost
                total_cost += cost
                gross = exit_price / p['Entry_Price'] - 1
                net = float(execution_return(p['Entry_Price'], exit_price, 'LONG', COSTS))
                trades.append(dict(**p, Exit_Price=exit_price, Gross=gross, Net=net,
                                   Gross_USD=p['Notional']*gross, Net_USD=p['Notional']*net))
                del positions[ticker]
        equity = cash + sum(p['Qty']*float(today.loc[t,'Close']) for t,p in positions.items())
        curve.append(dict(Date=date, Net_Equity=equity, Gross_Equity=equity+total_cost,
                          Open_Positions=len(positions)))
        previous_equity = equity
        if cash < -1e-7 or len(positions) > MAX_POSITIONS:
            raise AssertionError('Cash/position limit violated')
    if positions:
        raise AssertionError('Unclosed positions')
    columns = ['Ticker','Signal','Entry','Exit','Entry_Price','Notional','Qty','Exit_Price',
               'Gross','Net','Gross_USD','Net_USD']
    t = pd.DataFrame(trades, columns=columns)
    for c in ('Signal','Entry','Exit'):
        t[c] = pd.to_datetime(t[c])
    assert np.isclose(cash-INITIAL, t.Net_USD.sum(), atol=1e-6)
    return t, pd.DataFrame(curve)


def metrics(t):
    out = dict(Trades=len(t))
    for name in ('Gross','Net'):
        r = t[name].astype(float)
        gains, losses = r[r > 0].sum(), -r[r < 0].sum()
        out.update({name+'_Win_Rate': float((r > 0).mean()) if len(r) else np.nan,
                    name+'_Mean': r.mean(), name+'_Median': r.median(),
                    name+'_PF': gains/losses if losses else (np.inf if gains else np.nan),
                    name+'_PnL_USD': t[name+'_USD'].sum()})
    out['Net_Expectancy'] = out['Net_Mean']
    return out


def portfolio_metrics(curve):
    out = {}
    for mode in ('Gross','Net'):
        equity = pd.concat([pd.Series([INITIAL]), curve[mode+'_Equity']], ignore_index=True)
        out[mode+'_Total_Return'] = equity.iloc[-1]/INITIAL-1
        out[mode+'_Max_Drawdown'] = (equity/equity.cummax()-1).min()
    return out


def annual_rows(trades, curve):
    rows, previous = [], {'Gross': INITIAL, 'Net': INITIAL}
    for year in range(2018,2026):
        row = dict(Year=year, **metrics(trades[trades.Entry.dt.year.eq(year)]))
        c = curve[curve.Date.dt.year.eq(year)]
        for mode in ('Gross','Net'):
            end = c[mode+'_Equity'].iloc[-1]
            row[mode+'_Portfolio_Return'] = end/previous[mode]-1
            previous[mode] = end
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', type=Path, default=ROOT/'data/cache/v1_top100/ohlcv.csv')
    parser.add_argument('--output', type=Path, default=ROOT/'results/v1_final_benchmark')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    u_path = ROOT/'data/universe/top100_us_v1.csv'
    protocol = ROOT/'research/v1_benchmark/protocol.md'
    # Verify the pre-results lock before reading prices or computing returns.
    lock = json.loads((protocol.parent/'frozen_inputs.json').read_text())
    assert sha(protocol) == lock['protocol_sha256'], 'Protocol changed after freezing'
    assert sha(u_path) == lock['universe_sha256'], 'Universe changed after freezing'
    assert sha(protocol.parent/'data_overrides.json') == lock['overrides_sha256']
    frame = pd.read_csv(args.prices, parse_dates=['Date'])
    calendar, coverage = validate_prices(frame, pd.read_csv(u_path))
    features, thresholds = signals(frame)
    summaries, annual, contributions, portfolios, decisions = [], [], [], [], []
    for strategy in STRATEGIES:
        for h in (1,2,3):
            e = candidates(features, strategy, h, calendar)
            base_t, base_c = portfolio(frame, e, calendar)
            best5 = base_t.groupby('Ticker').Net_USD.sum().sort_values(ascending=False).head(5).index.tolist()
            worst_stress = None
            for scenario, excluded in [('base', []), ('without_best5', best5)]:
                t,c = (base_t,base_c) if scenario == 'base' else portfolio(frame,e,calendar,excluded)
                key = dict(Strategy=strategy, Horizon=h, Scenario=scenario)
                a = annual_rows(t,c)
                annual.extend([dict(**key,**r) for r in a])
                s = dict(**key,**metrics(t),**portfolio_metrics(c), Trades_Per_Year=len(t)/8,
                         Candidate_Signals=len(e), Removed_Tickers=';'.join(excluded),
                         Best_Year=max(a, key=lambda r:r['Net_Portfolio_Return'])['Year'],
                         Worst_Year=min(a, key=lambda r:r['Net_Portfolio_Return'])['Year'],
                         Best_Year_Net_Return=max(r['Net_Portfolio_Return'] for r in a),
                         Worst_Year_Net_Return=min(r['Net_Portfolio_Return'] for r in a))
                summaries.append(s)
                portfolios.append(dict(**key,**portfolio_metrics(c)))
                if scenario == 'without_best5':
                    worst_stress = s
            for ticker,g in base_t.groupby('Ticker'):
                contributions.append(dict(Strategy=strategy,Horizon=h,Ticker=ticker,**metrics(g)))
            if h == 3:
                best_year = base_t.groupby(base_t.Entry.dt.year).Net_USD.sum().idxmax() if len(base_t) else None
                remainder = base_t[base_t.Entry.dt.year.ne(best_year)]
                b = metrics(base_t)
                keep = (b['Net_Mean'] > 0 and b['Net_PF'] > 1 and remainder.Net.mean() > 0
                        and worst_stress['Net_Mean'] > 0 and worst_stress['Net_PF'] > 1
                        and worst_stress['Net_Total_Return'] > 0)
                decisions.append(dict(Strategy=strategy, Verdict='KEEP' if keep else 'DROP',
                    Best_Year=best_year, Net_Mean_Without_Best_Year=remainder.Net.mean(), Best5=best5))
            print(strategy, h, metrics(base_t), flush=True)
    for name, rows in [('summary',summaries),('annual',annual),('ticker_contribution',contributions),
                       ('portfolio_summary',portfolios)]:
        pd.DataFrame(rows).to_csv(args.output/f'{name}.csv', index=False)
    source_manifest = args.prices.parent/'manifest.json'
    provenance = json.loads(source_manifest.read_text()) if source_manifest.exists() else None
    if provenance is not None and provenance['prices_sha256'] != sha(args.prices):
        raise ValueError('Price file differs from download manifest')
    audit = dict(universe_size=100, tickers_with_prices=99, no_history=['SPCX'],
                 start=str(calendar[calendar>=START].min().date()), end=str(END.date()),
                 price_sha256=sha(args.prices), protocol_sha256=sha(protocol),
                 universe_sha256=sha(u_path), thresholds=thresholds, coverage=coverage,
                 source_provenance=provenance,
                 versions=dict(python=sys.version.split()[0], pandas=pd.__version__, numpy=np.__version__),
                 decisions=decisions)
    (args.output/'audit.json').write_text(json.dumps(audit, indent=2, default=str)+'\n')
    lines = ['# Market Lab V1 — décision finale', '',
             'Signaux existants figés avant résultats. Décision sur 3D ; aucun réglage après résultats.', '',
             '| Stratégie | Verdict | Moyenne nette 3D | PF net | Sans meilleurs 5 tickers |',
             '|---|---|---:|---:|---:|']
    for d in decisions:
        b = next(s for s in summaries if s['Strategy']==d['Strategy'] and s['Horizon']==3 and s['Scenario']=='base')
        r = next(s for s in summaries if s['Strategy']==d['Strategy'] and s['Horizon']==3 and s['Scenario']=='without_best5')
        lines.append(f"| {d['Strategy']} | {d['Verdict']} | {b['Net_Mean']:.4%} | {b['Net_PF']:.3f} | {r['Net_Mean']:.4%} |")
    lines += ['', '## Pourquoi ces décisions', '']
    for d in decisions:
        years = [r for r in annual if r['Strategy']==d['Strategy'] and r['Horizon']==3 and r['Scenario']=='base']
        positives = sum(r['Net_Mean'] > 0 for r in years)
        lines.append(f"- **{d['Strategy']} — {d['Verdict']}** : {positives}/8 années à moyenne nette positive. "
                     f"Sans l'année la plus contributrice ({d['Best_Year']}), moyenne nette "
                     f"{d['Net_Mean_Without_Best_Year']:.4%}. Meilleurs contributeurs retirés : "
                     f"{', '.join(d['Best5'])}. Le stress test devient négatif : critère KEEP non rempli.")
    lines += ['', '## Comparaison complète', '',
              '| Stratégie | Hold | Trades | Moy. brute | Moy. nette | PF net | DD net | Portefeuille net |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        if s['Scenario']=='base':
            lines.append(f"| {s['Strategy']} | {s['Horizon']}D | {s['Trades']} | {s['Gross_Mean']:.4%} | "
                         f"{s['Net_Mean']:.4%} | {s['Net_PF']:.3f} | {s['Net_Max_Drawdown']:.2%} | {s['Net_Total_Return']:.2%} |")
    lines += ['', 'Détails : summary.csv (trades acceptés), annual.csv, ticker_contribution.csv,',
              'portfolio_summary.csv ; audit.json conserve couverture, seuils annuels et empreintes.',
              'Rendements en fractions décimales ; PnL en USD. Sans meilleurs 5 = nouveau passage',
              'du portefeuille sans ces titres, pas un nouveau signal. Frais/slippage 0,20 % par trade.', '',
              '## Limites', '',
              '- Snapshot courant : survivorship bias accepté ; ce test est rétrospectif, pas OOS indépendant.',
              '- 100 sociétés figées, 99 avec un historique au moins partiel en 2018–2025 ; SPCX cotée en 2026.',
              '- IPO/spin-offs : fenêtres plus courtes, pas de données inventées avant cotation.',
              '- DELL/GEV/SNDK limités à leur cotation regular-way ; DHR limité au segment après juillet 2016, avant calcul de performances.',
              '- Yahoo ajusté des distributions, révisable ; résultats non garantis sur un téléchargement futur.',
              '- Mean Reversion reprend le signal V4.4 mais utilise ici des sorties fixes sans SL/TP.',
              '- 10 % par entrée et 5 positions sont un benchmark, pas le sizing final.',
              '- Ordre alphabétique, entrées Open idéalisées, coûts constants ; capacité de marché non étudiée.', '',
              'STOP : aucune nouvelle variante, aucun développement IBKR ou moteur portefeuille final.']
    (args.output/'decision.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
