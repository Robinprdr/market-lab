"""Audit all downloaded partitions without loading the entire panel."""
import json
import time
import numpy as np
import pandas as pd
from .common import CACHE,OUT,HERE,UNIVERSE,protocol,sha,write

def main():
    cfg=protocol();overrides=json.loads((HERE/'data_overrides.json').read_text());available=[];checks=[];all_quality=[]
    for t in pd.read_csv(UNIVERSE).ticker.tolist()+['SPY']:
        for y in range(2018,2027):
            p=CACHE/'1m'/t/f'{y}.parquet';meta=p.with_suffix('.json');m=json.loads(meta.read_text());f=pd.read_parquet(p)
            if m['feed']!='sip' or m['adjustment']!='split' or m['asof']!=cfg['symbol_asof']:raise ValueError('Wrong source contract')
            if p.stat().st_size!=m['bytes']:raise ValueError('Cache file size changed')
            m['sha256']=sha(p);write(meta,m)
            q=pd.read_csv(p.with_suffix('.quality.csv'));q['included_in_research']=True;q['excluded_reason']=''
            start=overrides.get(t,{}).get('start','2018-01-01')
            if t in overrides:
                prefix=q.session.fillna('').astype(str).lt(start);q.loc[prefix,'included_in_research']=False;q.loc[prefix,'excluded_reason']=overrides[t]['reason']
            all_quality.append(q)
            if f.empty:available.append(dict(ticker=t,year=y,bars=0,start='',end='',status='NO_SOURCE_DATA',excluded_prefix_bars=0));continue
            if f.Date.duplicated().any():raise ValueError('Duplicate cache timestamps')
            if not ((f.Date>=f.Session_Open)&(f.Date<f.Session_Close)).all():raise ValueError('Out-of-session bar')
            valid=f[f.Session.ge(start)]
            available.append(dict(ticker=t,year=y,bars=len(valid),start=str(valid.Date.min()) if len(valid) else '',end=str(valid.Date.max()) if len(valid) else '',status='AVAILABLE' if len(valid) else 'EXCLUDED_PREDECESSOR_OR_WHEN_ISSUED',excluded_prefix_bars=len(f)-len(valid),minimum_split_adjusted_price=float(valid.Low.min()) if len(valid) else None,minimum_volume=float(valid.Volume.min()) if len(valid) else None,vwap_equals_close_fraction=float(valid.VWAP.eq(valid.Close).mean()) if len(valid) else None,vwap_outside_range=int(((valid.VWAP<valid.Low-.0001)|(valid.VWAP>valid.High+.0001)).sum()) if len(valid) else 0))
            # Split-adjustment continuity sanity screen, not a filter tuned to returns.
            g=valid.groupby('Session').agg(Open=('Open','first'),Close=('Close','last'))
            gaps=g.Open/g.Close.shift()-1
            for day,gap in gaps[gaps.abs()>.5].items():checks.append(dict(ticker=t,session=day,gap=float(gap),note='Large split-adjusted overnight discontinuity: investigate; no overnight return used'))
    pd.concat(all_quality,ignore_index=True).to_csv(OUT/'data_quality.csv',index=False)
    frame=pd.DataFrame(available);frame.to_csv(OUT/'availability.csv',index=False)
    pd.DataFrame(checks,columns=['ticker','session','gap','note']).to_csv(OUT/'adjustment_checks.csv',index=False)
    write(OUT/'cache_integrity.json',dict(universe_sha256=sha(UNIVERSE),overrides_sha256=sha(HERE/'data_overrides.json'),partitions=len(frame),usable_regular_bars=int(frame.bars.sum()),excluded_prefix_bars=int(frame.excluded_prefix_bars.sum()),tickers_with_data=int(frame[frame.bars.gt(0)&frame.ticker.ne('SPY')].ticker.nunique()),data_quality_sha256=sha(OUT/'data_quality.csv')))
    print('CACHE AUDIT COMPLETE',int(frame.bars.sum()),'usable minute bars',flush=True)

if __name__=='__main__':main()
