"""Frozen Breakout A/B factor study; no optimization, costs or portfolio sizing.
A: Close[t] > max(High[t-20:t-1]), inclusive 20 preceding sessions.
B: A and ATR_Pct_10D[t-1] < median(ATR_Pct_10D[t-60:t-1]).
ATR uses the repository's simple moving mean of true range, divided by Close.
Episodes are maximal contiguous A-true runs, a diagnostic proxy only.
Run from repo root with --ohlc-csv PATH. Requires pandas and numpy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5)
CORE_SHA = 'ce157c4630580cf431a841af42c18db627c68bee'


def features(frame):
    x = frame.sort_values('Date').reset_index(drop=True).copy()
    x['Session'] = np.arange(len(x))
    previous = x.Close.shift(1)
    tr = pd.concat([x.High-x.Low, (x.High-previous).abs(), (x.Low-previous).abs()], axis=1).max(axis=1)
    x['ATR_Pct_10D'] = tr.rolling(10, min_periods=10).mean()/x.Close
    x['Previous_High_20D'] = x.High.shift(1).rolling(20, min_periods=20).max()
    x['Prior_ATR'] = x.ATR_Pct_10D.shift(1)
    x['Prior_ATR_Median_60D'] = x.ATR_Pct_10D.rolling(60, min_periods=60).median().shift(1)
    x['Compression_Valid'] = x.Prior_ATR_Median_60D.notna()
    x['A'] = x.Close.gt(x.Previous_High_20D)
    x['B'] = x.A & x.Prior_ATR.lt(x.Prior_ATR_Median_60D)
    starts = x.A & ~x.A.shift(1, fill_value=False)
    x['Episode_Start'] = x.Date.where(starts).ffill().where(x.A)
    return x


def check(x):
    high, low, close = (x[c].to_numpy() for c in ('High', 'Low', 'Close'))
    tr = np.array([high[0]-low[0]] + [max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])) for i in range(1,len(x))])
    atr = np.full(len(x), np.nan)
    for i in range(9,len(x)):
        atr[i] = np.mean(tr[i-9:i+1])/close[i]
    a, b = np.zeros(len(x), bool), np.zeros(len(x), bool)
    for i in range(20,len(x)):
        a[i] = close[i] > max(high[i-20:i])
        assert x.Previous_High_20D.iloc[i] == max(high[i-20:i])
        if i >= 69:
            assert np.isclose(x.Prior_ATR_Median_60D.iloc[i], np.median(atr[i-60:i]))
            b[i] = a[i] and atr[i-1] < np.median(atr[i-60:i])
    assert np.array_equal(a,x.A) and np.array_equal(b,x.B)
    for end in (75,len(x)//2,len(x)-5):
        assert np.array_equal(features(x.iloc[:end])[['A','B']], x[['A','B']].iloc[:end])
    cut = len(x)//2
    y = x.copy()
    y.loc[cut:,['Open','High','Low','Close']] *= 7
    assert np.array_equal(features(y)[['A','B']].iloc[:cut],x[['A','B']].iloc[:cut])
    # Changes to the breakout day's OHLC must not alter either reference.
    z = features(y)
    assert z.Previous_High_20D.iloc[cut] == x.Previous_High_20D.iloc[cut]
    assert z.Prior_ATR.iloc[cut] == x.Prior_ATR.iloc[cut]
    assert z.Prior_ATR_Median_60D.iloc[cut] == x.Prior_ATR_Median_60D.iloc[cut]


def stats(x, name, year='ALL'):
    return [{'Group':name,'Year':year,'Horizon':h,'N':len(x),'Mean':x[f'Future_Return_{h}D'].mean(),
             'Median':x[f'Future_Return_{h}D'].median(),'Win_Rate':x[f'Future_Return_{h}D'].gt(0).mean()} for h in HORIZONS]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core-csv',type=Path,default=Path('results/short_momentum/short_momentum_v1_research_core.csv'))
    p.add_argument('--ohlc-csv',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,default=Path('results/breakout/initial'))
    args = p.parse_args()
    blob = args.core_csv.read_bytes()
    assert hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest() == CORE_SHA
    core = pd.read_csv(args.core_csv,parse_dates=['Date'])
    raw = pd.read_csv(args.ohlc_csv,parse_dates=['Date'])
    assert not raw.duplicated(['Date','Ticker']).any() and not core.duplicated(['Date','Ticker']).any()
    assert set(raw.Ticker) == set(core.Ticker)
    assert raw[['Open','High','Low','Close']].notna().all().all()
    assert (raw[['Open','High','Low','Close']]>0).all().all()
    assert raw.High.ge(raw[['Open','Close','Low']].max(axis=1)).all()
    assert raw.Low.le(raw[['Open','Close','High']].min(axis=1)).all()
    calendars = [tuple(g.sort_values('Date').Date) for _,g in raw.groupby('Ticker')]
    assert all(c == calendars[0] for c in calendars)
    frames = []
    for _,g in raw.groupby('Ticker'):
        x = features(g)
        check(x)
        # No forward columns are available to the signal builder.
        x['Entry_Date'] = x.Date.shift(-1)
        x['Entry_Open'] = x.Open.shift(-1)
        for h in HORIZONS:
            x[f'Exit_Date_{h}D'] = x.Date.shift(-h)
            x[f'Future_Return_{h}D'] = x.Close.shift(-h)/x.Open.shift(-1)-1
        for i in np.flatnonzero(x.A):
            if i+5 >= len(x): continue
            assert x.Entry_Date.iloc[i] == x.Date.iloc[i+1]
            assert x.Entry_Open.iloc[i] == x.Open.iloc[i+1]
            for h in HORIZONS:
                assert x[f'Exit_Date_{h}D'].iloc[i] == x.Date.iloc[i+h]
                assert x[f'Future_Return_{h}D'].iloc[i] == x.Close.iloc[i+h]/x.Open.iloc[i+1]-1
        frames.append(x)
    d = core.merge(pd.concat(frames),on=['Date','Ticker'],how='left',suffixes=('_Core',''),validate='one_to_one',indicator=True)
    assert d._merge.eq('both').all()
    reconciliation = {}
    for h in HORIZONS:
        col = f'Future_Return_{h}D'
        assert d[col].notna().all() and np.isclose(d[col],d[col+'_Core'],atol=1e-12,rtol=0).all()
        reconciliation[col] = float((d[col]-d[col+'_Core']).abs().max())
    assert not (d.B & ~d.A).any()
    d['Year'] = d.Date.dt.year
    metrics, counts = [], []
    summary = {'core_sha':CORE_SHA,'ohlc_sha256':hashlib.sha256(args.ohlc_csv.read_bytes()).hexdigest(),
               'baseline_rows':len(d),'period':[str(d.Date.min().date()),str(d.Date.max().date())],
               'missing_high_reference':int(d.Previous_High_20D.isna().sum()),
               'missing_compression_reference':int((~d.Compression_Valid).sum()),
               'A_missing_compression':int((d.A & ~d.Compression_Valid).sum()),
               'intersection':int(d.B.sum()),'A_only':int((d.A & ~d.B).sum()),'B_only':0,
               'reconciliation':reconciliation,'groups':{}}
    groups = {'BASELINE':d,'BASELINE_COMPRESSION_VALID':d[d.Compression_Valid], 'A':d[d.A],'B':d[d.B]}
    for name,x in groups.items():
        metrics += stats(x,name)
        for year in sorted(d.Year.unique()):
            z = x[x.Year.eq(year)]
            metrics += stats(z,name,int(year))
            counts.append({'Group':name,'Year':int(year),'N':len(z),'Tickers':z.Ticker.nunique(),'Dates':z.Date.nunique()})
        if name not in ('A','B'): continue
        x = x.sort_values(['Ticker','Date'])
        ep = x.groupby(['Ticker','Episode_Start']).size()
        gaps = x.groupby('Ticker').Session.diff()
        holds = {}
        for h in HORIZONS:
            kept = 0
            for _,z in x.groupby('Ticker'):
                last = -100000
                for session in z.Session:
                    # Exit at close s+h; next entry allowed strictly after it.
                    if session-last >= h:
                        kept += 1
                        last = session
            holds[str(h)] = {'retained':kept,'excluded':len(x)-kept}
        summary['groups'][name] = {'observations':len(x),'tickers':x.Ticker.nunique(),'dates':x.Date.nunique(),
             'mean_per_year':len(x)/d.Year.nunique(),'A_run_episodes':len(ep),'episodes_with_multiple_signals':int(ep.gt(1).sum()),
             'signals_beyond_first_in_A_run':int((ep-1).sum()),'max_signals_in_A_run':int(ep.max()),
             'consecutive_signal_pairs':int(gaps.eq(1).sum()),'holds':holds}
    summary['checks'] = 'independent scalar signal, prefix invariance, future mutation, t-day reference invariance, t+1 alignment, core reconciliation passed'
    args.output_dir.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(metrics).to_csv(args.output_dir/'statistics.csv',index=False)
    pd.DataFrame(counts).to_csv(args.output_dir/'annual_counts.csv',index=False)
    d[d.A].drop(columns='_merge').to_csv(args.output_dir/'observations.csv',index=False)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2,default=int)+'\n')
    print(json.dumps(summary,indent=2,default=int))
    print(pd.DataFrame(metrics).query("Year == 'ALL'").to_string(index=False))


if __name__ == '__main__':
    main()
