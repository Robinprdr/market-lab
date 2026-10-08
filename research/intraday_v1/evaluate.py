"""Signal-close / next-open execution, long entry-notional returns, no overnight."""
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit
from .common import CACHE,OUT,cost,protocol

@njit(cache=True)
def outcomes(opens,closes,complete,ticker,session,horizons):
    n=len(opens);returns=np.full((len(horizons),n),np.nan);exit_index=np.full((len(horizons),n),-1,np.int32)
    for i in range(n-1):
        if ticker[i]!=ticker[i+1] or session[i]!=session[i+1] or not complete[i+1] or not np.isfinite(opens[i+1]) or opens[i+1]<=0:continue
        last=i+1
        while last+1<n and ticker[last+1]==ticker[i] and session[last+1]==session[i]:last+=1
        for hidx in range(len(horizons)):
            h=horizons[hidx];end=last if h==0 else i+h
            if end>last:continue
            valid=True
            for k in range(i+1,end+1):
                if not complete[k]:valid=False;break
            if valid and np.isfinite(closes[end]):
                returns[hidx,i]=closes[end]/opens[i+1]-1;exit_index[hidx,i]=end
    return returns,exit_index

@njit(cache=True)
def scan(atoms,conditions,counts,hindex,returns,exits,tickers,fee,ntickers):
    nrules=len(hindex);out=np.zeros((nrules,8));contribution=np.zeros((nrules,ntickers));ticker_count=np.zeros((nrules,ntickers))
    for r in range(nrules):
        busy=-1;previous=-1;h=hindex[r]
        for i in range(atoms.shape[1]):
            if tickers[i]!=previous:busy=-1;previous=tickers[i]
            if i+1<=busy:continue
            signal=True
            for j in range(counts[r]):
                if not atoms[conditions[r,j],i]:signal=False;break
            if not signal:continue
            gross=returns[h,i]
            if not np.isfinite(gross):continue
            busy=exits[h,i];net=gross-fee;stress=gross-2*fee
            out[r,0]+=1;out[r,1]+=gross;out[r,2]+=net;out[r,3]+=net*net;out[r,4]+=net>0
            out[r,5]+=max(net,0);out[r,6]+=max(-net,0);out[r,7]+=stress
            contribution[r,tickers[i]]+=net;ticker_count[r,tickers[i]]+=1
    return out,contribution,ticker_count

@njit(cache=True)
def selected(mask,gross,exits,tickers):
    chosen=np.zeros(len(mask),np.bool_);busy=-1;previous=-1
    for i in range(len(mask)):
        if tickers[i]!=previous:busy=-1;previous=tickers[i]
        if i+1<=busy or not mask[i] or not np.isfinite(gross[i]):continue
        chosen[i]=True;busy=exits[i]
    return chosen

def paths(stage):
    cfg=protocol()
    if stage not in ('exploration','validation','final'):raise ValueError('Invalid stage')
    begin,end=cfg[stage]
    return [p for p in sorted((CACHE/'features').glob('*.parquet')) if begin[:7]<=p.stem<=end[:7]]

def prepare(f,cfg):
    f=f.sort_values(['Ticker','Date']).reset_index(drop=True)
    # Both liquidity and range proxy are observed at the signal close, not at a future bar.
    eligible=f.Feature_Eligible.to_numpy(bool)&f.DollarVolume.ge(cfg['liquidity_dollar_volume']).to_numpy()&f.range_pct.le(cfg['max_bar_range_pct']).to_numpy()&f.Volume.gt(0).to_numpy()
    universe=pd.read_csv(__import__('research.intraday_v1.common',fromlist=['UNIVERSE']).UNIVERSE).ticker.tolist()
    t=f.Ticker.map({x:i for i,x in enumerate(universe)}).to_numpy(np.int32)
    s=pd.factorize(f.Session)[0].astype(np.int32)
    returns,exits=outcomes(f.Open.to_numpy(float),f.Close.to_numpy(float),f.Complete.to_numpy(bool),t,s,np.array(cfg['horizons_bars'],np.int32))
    return f,eligible,t,returns,exits

def condition_mask(f,condition):
    name,op,value=condition;s=f[name].to_numpy(float)
    if op=='>=':return s>=value
    if op=='<=':return s<=value
    if op=='>':return s>value
    if op=='<':return s<value
    raise ValueError('Unsupported predicate')

def trade_rows(f,rule,cfg):
    f,eligible,t,returns,exits=prepare(f,cfg);mask=eligible.copy()
    for atom in rule['conditions']:mask &= condition_mask(f,atom)
    h=cfg['horizons_bars'].index(rule['horizon_bars']);keep=selected(mask,returns[h],exits[h],t);i=np.flatnonzero(keep);e=exits[h,i]
    result=pd.DataFrame(dict(candidate=rule['id'],ticker=f.Ticker.iloc[i].to_numpy(),session=f.Session.iloc[i].to_numpy(),signal_time=f.Bar_End.iloc[i].to_numpy(),entry_time=f.Date.iloc[i+1].to_numpy(),exit_time=f.Bar_End.iloc[e].to_numpy(),entry=f.Open.iloc[i+1].to_numpy(),exit=f.Close.iloc[e].to_numpy(),gross=returns[h,i]))
    result['net']=result.gross-cost(cfg);result['stress_net']=result.gross-2*cost(cfg)
    result['holding_minutes']=(pd.to_datetime(result.exit_time,utc=True)-pd.to_datetime(result.entry_time,utc=True)).dt.total_seconds()/60
    if not result.empty:
        assert (pd.to_datetime(result.signal_time,utc=True)==pd.to_datetime(result.entry_time,utc=True)).all()
        assert (pd.to_datetime(result.entry_time,utc=True).dt.tz_convert('America/New_York').dt.date==pd.to_datetime(result.exit_time,utc=True).dt.tz_convert('America/New_York').dt.date).all()
    return result

def stats(trades):
    n=len(trades)
    if not n:return dict(trades=0,win_rate=None,average_gross=None,average_net=None,median_net=None,pf_net=None,expectancy=None,stress_average_net=None,signal_drawdown=None)
    net=trades.net;loss=-net[net<0].sum();equity=trades.sort_values(['exit_time','ticker']).net.cumsum();peak=equity.cummax().clip(lower=0)
    return dict(trades=n,win_rate=float((net>0).mean()),average_gross=float(trades.gross.mean()),average_net=float(net.mean()),median_net=float(net.median()),pf_net=float(net[net>0].sum()/loss) if loss else None,expectancy=float(net.mean()),stress_average_net=float(trades.stress_net.mean()),signal_drawdown=float((equity-peak).min()))

def concentration(trades):
    sums=trades.groupby('ticker').net.sum().sort_values(ascending=False);positive=sums.clip(lower=0).sum();top=sums.head(5)
    reduced=trades[~trades.ticker.isin(top.index)]
    return dict(top_ticker_share=float(sums.iloc[0]/positive) if positive else 1.,top5_share=float(top.clip(lower=0).sum()/positive) if positive else 1.,top5_tickers=list(top.index),remove_top5_average_net=float(reduced.net.mean()) if len(reduced) else None,remove_top5_trades=len(reduced))
