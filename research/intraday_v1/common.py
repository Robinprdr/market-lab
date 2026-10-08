import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
CACHE=ROOT/'data/cache/intraday_v1'
OUT=ROOT/'results/intraday_v1'
UNIVERSE=ROOT/'data/universe/top100_us_v1.csv'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False,default=str)+'\n')
    temporary.replace(path)

def protocol():
    obj=json.loads((OUT/'protocol.json').read_text())
    if obj['universe_sha256']!=sha(UNIVERSE):raise ValueError('Universe changed')
    return obj

def initialize(end):
    OUT.mkdir(parents=True,exist_ok=True);CACHE.mkdir(parents=True,exist_ok=True)
    target=OUT/'protocol.json'
    if target.exists():return protocol()
    obj=dict(version=1,universe_sha256=sha(UNIVERSE),feed='sip',adjustment='split',symbol_asof='2026-10-02',
        exploration=['2018-01-01','2023-12-31'],validation=['2024-01-01','2025-12-31'],final=['2026-01-01',end],
        source_minutes=1,search_minutes=5,horizons_bars=[3,6,12,18,24,0],
        base_cost=dict(commission_bps_per_side=3.5,half_spread_bps_per_side=1.,slippage_bps_per_side=2.5),
        stress_multiple=2,liquidity_dollar_volume=100000.,max_bar_range_pct=.05,
        seed=20261008,maximum_variants=6000,maximum_candidates=10,train_min_trades=1000,
        train_min_pf=1.10,train_positive_years=4,train_top_ticker_share=.30,
        validation_min_trades=300,validation_min_pf=1.10,validation_top_ticker_share=.40,
        final_min_trades=100,final_min_pf=1.15,
        portfolio=dict(capital=10000.,notional=1000.,maximum_positions=5,leverage=0),
        research='LONG continuity only; no retuning after exploration; same-day exits',
        limits=['Current Top100 snapshot has survivorship bias','2024–2026 calendar periods were seen in earlier families; no fully independent prospective proof','Bars do not identify bid/ask spread; costs are scenarios','Fixed notional signal study assumes fractional shares; standardized research portfolio, not execution-ready'])
    write(target,obj);return obj

def cost(cfg):return 2*sum(cfg['base_cost'].values())/10000
