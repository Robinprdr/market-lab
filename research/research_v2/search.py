"""Bounded deterministic beam search. This module receives exploration only."""
import hashlib
import json
import numpy as np
import pandas as pd


def identifier(rules,horizon):
    return hashlib.sha256(json.dumps([rules,horizon],sort_keys=True).encode()).hexdigest()[:12]


def rule_mask(frame,rules):
    mask=np.ones(len(frame),dtype=bool)
    for r in rules:
        x=frame[r['feature']].to_numpy(float)
        if r['op']=='>':test=x>r['threshold']
        elif r['op']=='>=':test=x>=r['threshold']
        elif r['op']=='<=':test=x<=r['threshold']
        else:raise ValueError('Unknown operator')
        mask &= np.isfinite(x)&test
    return mask


class Lab:
    def __init__(self,features,kind,period,horizons,cost):
        self.kind=kind;self.cost=cost;self.period=period
        day=features.Date.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d') if features.Date.dt.tz is not None else features.Date.dt.strftime('%Y-%m-%d')
        self.f=features[day.between(*period)&~features.Ticker.eq('SPY')].sort_values(['Ticker','Date']).reset_index(drop=True)
        f=self.f;self.n=len(f);self.horizons=horizons
        self.entry=np.arange(self.n)+1;self.exits={};self.returns={};self.valid={}
        ticker=f.Ticker.to_numpy();op=f.Open.to_numpy();cl=f.Close.to_numpy()
        date=f.Date.dt.tz_convert('America/New_York').dt.tz_localize(None) if f.Date.dt.tz is not None else f.Date
        self.years=date.dt.year.to_numpy();self.sessions=date.dt.normalize()
        self.session_count=self.sessions.nunique()
        if kind=='intraday':
            end=f.groupby(['Ticker','Session']).Date.transform(lambda x:x.index.max()).to_numpy(int)
            sess=f.Session.to_numpy()
        for h in horizons:
            ex=np.minimum(np.arange(self.n)+h,end) if kind=='intraday' and h else (end.copy() if kind=='intraday' else np.arange(self.n)+h)
            ok=(self.entry<self.n)&(ex<self.n)
            idx=np.flatnonzero(ok)
            ok[idx] &= ticker[idx]==ticker[ex[idx]]
            if kind=='intraday':ok[idx] &= (sess[idx]==sess[self.entry[idx]])&(sess[idx]==sess[ex[idx]])&(self.entry[idx]<=ex[idx])
            ret=np.full(self.n,np.nan);idx=np.flatnonzero(ok)
            ret[idx]=cl[ex[idx]]/op[self.entry[idx]]-1
            self.exits[h]=ex;self.returns[h]=ret;self.valid[h]=ok&np.isfinite(ret)

    def select(self,mask,h):
        idx=np.flatnonzero(mask&self.valid[h]);chosen=[];busy=-1
        for i in idx:
            if self.entry[i]>busy:
                chosen.append(i);busy=self.exits[h][i]
        return np.asarray(chosen,dtype=int)

    def stats(self,selected,h):
        r=self.returns[h][selected];net=r-self.cost
        loss=-net[net<0].sum();gain=net[net>0].sum()
        annual={str(y):float(net[self.years[self.entry[selected]]==y].mean()) for y in sorted(set(self.years)) if np.any(self.years[self.entry[selected]]==y)}
        ticker=self.f.Ticker.to_numpy()[selected]
        contrib=pd.Series(net).groupby(ticker).sum() if len(net) else pd.Series(dtype=float)
        pos=contrib.clip(lower=0)
        return dict(trades=len(r),trades_per_year=len(r)/max(1,len(set(self.years))),win_rate=float(np.mean(net>0)) if len(r) else None,
                    avg_gross=float(r.mean()) if len(r) else None,avg_net=float(net.mean()) if len(r) else None,
                    median_net=float(np.median(net)) if len(r) else None,pf_net=float(gain/loss) if loss else (999. if gain else 0.),
                    positive_years=sum(v>0 for v in annual.values()),annual=annual,
                    ticker_count=len(contrib),top_ticker_profit_share=float(pos.max()/pos.sum()) if pos.sum()>0 else 1.)

    def details(self,selected,h):
        f=self.f;entry=self.entry[selected];ex=self.exits[h][selected];r=self.returns[h][selected]
        t=pd.DataFrame(dict(Ticker=f.Ticker.iloc[selected].to_numpy(),Signal=f.Date.iloc[selected].to_numpy(),Entry=f.Date.iloc[entry].to_numpy(),Exit=f.Date.iloc[ex].to_numpy(),Gross=r,Net=r-self.cost))
        t['Year']=self.years[entry]
        if self.kind=='intraday':
            t['Signal']=f.Bar_End.iloc[selected].to_numpy();t['Exit']=f.Bar_End.iloc[ex].to_numpy()
            t['Holding_Minutes']=(pd.to_datetime(t.Exit)-pd.to_datetime(t.Entry)).dt.total_seconds()/60
            m=pd.to_datetime(t.Entry,utc=True).dt.tz_convert('America/New_York');slot=m.dt.hour*60+m.dt.minute
            t['Time_Bucket']=pd.cut(slot,[570,630,720,840,930,960],labels=['09:30-10:30','10:30-12:00','12:00-14:00','14:00-15:30','15:30-16:00'],right=False).astype(str)
        # Fixed equal-notional sleeves, mark-to-market, no final portfolio allocation.
        timeline=pd.DatetimeIndex(sorted(f.Date.unique()));delta=np.zeros(len(timeline))
        close=f.Close.to_numpy();opened=f.Open.to_numpy()
        for e,x in zip(entry,ex):
            prices=close[e:x+1];previous=np.r_[opened[e],prices[:-1]]
            increment=(prices-previous)/opened[e]/100
            increment[0]-=self.cost/200;increment[-1]-=self.cost/200
            slots=timeline.get_indexer(f.Date.iloc[e:x+1]);np.add.at(delta,slots,increment)
        equity=np.r_[1.,1+delta.cumsum()];dd=float(np.min(equity/np.maximum.accumulate(equity)-1))
        return t,dd


def explore(lab,names,config,lab_config,anchor):
    cfg=config['search'];base=rule_mask(lab.f,[anchor]);atoms=[];masks=[]
    for feature in names:
        if feature==anchor['feature']:continue
        values=lab.f[feature].replace([np.inf,-np.inf],np.nan).dropna()
        if values.nunique()<2:continue
        for threshold in sorted(set(float(values.quantile(q)) for q in cfg['train_quantiles'])):
            for op in cfg['operators']:
                atom=dict(feature=feature,op=op,threshold=threshold);m=rule_mask(lab.f,[atom])
                atoms.append(atom);masks.append(m)
    rows=[];records=[];seen=set();limit=cfg['maximum_variants_per_lab']
    def evaluate(combo):
        combo=tuple(sorted(combo))
        if combo in seen:return
        seen.add(combo);mask=base.copy()
        for i in combo:mask &= masks[i]
        rules=[anchor]+[atoms[i] for i in combo]
        for h in lab.horizons:
            if len(rows)>=limit:return
            ix=lab.select(mask,h);s=lab.stats(ix,h);cid=identifier(rules,h)
            score=(s['avg_net'] or -1)-.00005*(len(rules)-1)
            eligible=s['trades']>=lab_config['minimum_train_trades'] and s['pf_net']>=cfg['minimum_train_pf'] and s['positive_years']>=lab_config['minimum_positive_train_years'] and (s['avg_net'] or -1)>0
            row=dict(id=cid,horizon=h,conditions=len(rules),rules=json.dumps(rules,sort_keys=True),**s,score=score,eligible=eligible)
            rows.append(row);records.append((score,cid,combo,h,eligible))
        if len(seen)%100==0:print(lab.kind,'variants',len(rows),flush=True)
    for i in range(len(atoms)):evaluate((i,))
    # Retain at most one atom per feature as seeds, from exploration only.
    seeds=[];used=set()
    for score,cid,combo,h,eligible in sorted(records,key=lambda r:(-r[0],r[1])):
        if not eligible:continue
        i=combo[0];feature=atoms[i]['feature']
        if feature not in used:seeds.append(i);used.add(feature)
        if len(seeds)>=cfg['seed_features']:break
    for depth in range(2,cfg['maximum_extra_conditions']+1):
        beam=[]
        for score,cid,combo,h,eligible in sorted(records,key=lambda r:(-r[0],r[1])):
            if eligible and len(combo)==depth-1 and combo not in beam:beam.append(combo)
            if len(beam)>=cfg['beam_width']:break
        for combo in beam:
            for i in seeds:
                if atoms[i]['feature'] not in {atoms[j]['feature'] for j in combo}:evaluate(combo+(i,))
                if len(rows)>=limit:break
            if len(rows)>=limit:break
        if len(rows)>=limit:break
    final=[];selected_masks=[];lookup={r['id']:r for r in rows}
    for score,cid,combo,h,eligible in sorted(records,key=lambda r:(-r[0],r[1])):
        if not eligible:continue
        row=lookup[cid];rules=json.loads(row['rules']);m=rule_mask(lab.f,rules)&lab.valid[h]
        if any(np.sum(m&o)/max(1,np.sum(m|o))>cfg['maximum_train_signal_jaccard'] for o in selected_masks):continue
        ix=lab.select(m,h);_,dd=lab.details(ix,h)
        final.append(dict(id=cid,lab=lab.kind,rules=rules,horizon=h,conditions=len(rules),exploration=lab.stats(ix,h),exploration_drawdown=dd,variants_tested=len(rows)))
        selected_masks.append(m)
        if len(final)>=cfg['maximum_candidates']:break
    export=pd.DataFrame(rows)
    if len(export):export['annual']=export.annual.map(lambda x:json.dumps(x,sort_keys=True));export['variants_tested']=len(rows)
    return export,final
