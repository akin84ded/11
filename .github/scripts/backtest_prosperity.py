#!/usr/bin/env python3
"""Walk-forward test of Prosperity v3.8 daily core rules.
Intraday confirmation is evaluated by the Android app but MOEX intraday history is
not consistently available over a multi-year horizon; this report explicitly tests
the daily core, with a chronological out-of-sample split and realistic conservative fills.
"""
import csv, json, math, os, time
from datetime import date
from urllib.request import Request, urlopen

TICKERS=os.getenv("TICKERS","SBER,GAZP,LKOH,ROSN,NVTK,TATN,GMKN,MGNT,MOEX,CHMF,ALRS,MTSS,AFLT,VTBR").split(",")
FROM=os.getenv("FROM_DATE","2021-01-01")
HORIZON=int(os.getenv("HORIZON","20"))
ENTRY_DAYS=int(os.getenv("ENTRY_DAYS","10"))
FEE_SIDE=float(os.getenv("FEE_SIDE","0.0005"))
OOS_FRACTION=float(os.getenv("OOS_FRACTION","0.30"))
TODAY=date.today().isoformat()

def get_json(url):
    last=None
    for attempt in range(3):
        for scheme in ("https","http"):
            try:
                req=Request(url.replace("https://",scheme+"://"),headers={"User-Agent":"Prosperity-backtest/3.8"})
                with urlopen(req,timeout=25) as r:return json.loads(r.read().decode("utf-8"))
            except Exception as e:last=e
        time.sleep(1.0+attempt)
    raise RuntimeError(f"MOEX request failed: {last}")

def load(ticker):
    out=[];start=0
    while True:
        url=(f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
             f"?from={FROM}&till={TODAY}&interval=24&start={start}&iss.meta=off")
        obj=get_json(url);block=obj.get("candles",{});cols=block.get("columns",[]);rows=block.get("data",[])
        if not rows:break
        ix={k:i for i,k in enumerate(cols)}
        for r in rows:
            try:
                c={"date":str(r[ix["begin"]])[:10],"open":float(r[ix["open"]]),"high":float(r[ix["high"]]),
                   "low":float(r[ix["low"]]),"close":float(r[ix["close"]]),"volume":float(r[ix["volume"]])}
                if c["close"]>0:out.append(c)
            except (KeyError,IndexError,TypeError,ValueError):pass
        start+=len(rows)
        if len(rows)<500 or start>30000:break
    d={x["date"]:x for x in out}
    return [d[k] for k in sorted(d)]

def sma(a,end,p):
    if end<p:return float("nan")
    return sum(x["close"] for x in a[end-p:end])/p

def ema(a,end,p):
    """EMA seeded with the first p-period SMA, calculated only through end-1."""
    if end<p:return float("nan")
    v=sum(x["close"] for x in a[:p])/p;k=2.0/(p+1)
    for i in range(p,end):v=a[i]["close"]*k+v*(1-k)
    return v

def rsi(a,end,period=14):
    if end<=period:return float("nan")
    up=dn=0.0
    for i in range(1,period+1):
        d=a[i]["close"]-a[i-1]["close"]
        up+=max(0,d);dn+=max(0,-d)
    up/=period;dn/=period
    for i in range(period+1,end):
        d=a[i]["close"]-a[i-1]["close"]
        up=(up*(period-1)+max(0,d))/period
        dn=(dn*(period-1)+max(0,-d))/period
    return 100.0 if dn==0 else 100-100/(1+up/dn)

def indicators(a,end):
    p=a[end-1]["close"];s20=sma(a,end,20);s50=sma(a,end,50);s200=sma(a,end,200)
    rr=rsi(a,end);prev_r=rsi(a,end-1)
    macd=ema(a,end,12)-ema(a,end,26);prev_macd=ema(a,end-1,12)-ema(a,end-1,26)
    trs=[]
    for i in range(end-14,end):
        x=a[i];pr=a[i-1]
        trs.append(max(x["high"]-x["low"],abs(x["high"]-pr["close"]),abs(x["low"]-pr["close"])))
    atr=sum(trs)/14
    prior=a[max(0,end-21):end-1]
    support=min(x["low"] for x in prior) if prior else float("nan")
    resistance=max(x["high"] for x in prior) if prior else float("nan")
    vols=[x["volume"] for x in prior if x["volume"]>0]
    avgvol=sum(vols)/len(vols) if vols else 0
    lastvol=a[end-1]["volume"]
    score=0
    score+=2 if p>s20 else -2
    score+=2 if s20>s50 else -2
    score+=2 if p>s200 else -2
    score+=1 if macd>prev_macd else -1
    if 50<=rr<=70:score+=1
    elif rr>75:score-=2
    elif rr<30 and rr>prev_r:score+=1
    elif rr<50:score-=1
    if avgvol>0 and lastvol>avgvol*1.2 and p>a[end-2]["close"]:score+=1
    if resistance>0 and (resistance-p)/p<0.015:score-=1
    # Entry is based only on information available after the signal close.
    entry=min(p-0.25*atr,max(s20,support))
    if entry<=0 or entry>p:entry=p-0.25*atr
    return {"score":score,"price":p,"atr":atr,"entry":entry,"stop":max(0,entry-1.5*atr),
            "target":entry+3*atr,"rsi":rr,"macd":macd}

def make_trades(ticker,a,signal_end,start_idx=200):
    trades=[];i=start_idx
    while i<signal_end-2:
        z=indicators(a,i+1)
        if z["score"]<2:i+=1;continue
        fill=None;actual_entry=None
        for j in range(i+1,min(i+1+ENTRY_DAYS,signal_end)):
            if a[j]["low"]<=z["entry"]:
                fill=j;actual_entry=min(z["entry"],a[j]["open"]);break
        if fill is None:i+=1;continue
        stop,target=z["stop"],z["target"];exit_idx=None;exit_price=None;reason=None
        last=min(signal_end-1,fill+HORIZON)
        for j in range(fill,last+1):
            hs=a[j]["low"]<=stop;ht=a[j]["high"]>=target
            if hs and ht:exit_idx=j;exit_price=min(stop,a[j]["open"]);reason="both_same_bar_stop_first";break
            if hs:exit_idx=j;exit_price=min(stop,a[j]["open"]);reason="stop";break
            if ht:exit_idx=j;exit_price=max(target,a[j]["open"]);reason="target";break
        if exit_idx is None:exit_idx=last;exit_price=a[last]["close"];reason="time_exit"
        net=(exit_price*(1-FEE_SIDE))/(actual_entry*(1+FEE_SIDE))-1
        benchmark=a[exit_idx]["close"]/a[fill]["open"]-1 if a[fill]["open"] else 0
        trades.append({"ticker":ticker,"signal_date":a[i]["date"],"fill_date":a[fill]["date"],
          "exit_date":a[exit_idx]["date"],"score":z["score"],"entry":round(actual_entry,4),
          "stop":round(stop,4),"target":round(target,4),"exit":round(exit_price,4),
          "reason":reason,"net_pct":round(net*100,3),"benchmark_pct":round(benchmark*100,3),
          "bars_held":exit_idx-fill})
        i=exit_idx+1
    return trades

def stats(trades):
    if not trades:return {"trades":0,"win_rate_pct":0,"avg_net_pct":0,"median_net_pct":0,"profit_factor":None}
    rs=[x["net_pct"] for x in trades];wins=[x for x in rs if x>0]
    gp=sum(x for x in rs if x>0);gl=-sum(x for x in rs if x<0)
    eq=peak=1.0;dd=0.0
    for x in rs:eq*=1+x/100;peak=max(peak,eq);dd=min(dd,(eq/peak-1)*100)
    return {"trades":len(rs),"win_rate_pct":round(len(wins)/len(rs)*100,2),
      "avg_net_pct":round(sum(rs)/len(rs),3),"median_net_pct":round(sorted(rs)[len(rs)//2],3),
      "profit_factor":round(gp/gl,3) if gl else None,"max_drawdown_trade_sequence_pct":round(dd,2),
      "avg_benchmark_pct":round(sum(x["benchmark_pct"] for x in trades)/len(trades),3),
      "targets":sum(x["reason"]=="target" for x in trades),
      "stops":sum(x["reason"] in ("stop","both_same_bar_stop_first") for x in trades),
      "time_exits":sum(x["reason"]=="time_exit" for x in trades)}

def main():
    all_rows=[];all_trades=[];per=[]
    for ticker in TICKERS:
        try:
            a=load(ticker)
            if len(a)<260:
                per.append({"ticker":ticker,"bars":len(a),"status":"insufficient history"});continue
            split=max(220,min(len(a)-50,int(len(a)*(1-OOS_FRACTION))))
            train=make_trades(ticker,a,split)
            # OOS trades may use pre-split candles as indicator warm-up, but signals begin at split.
            oos=make_trades(ticker,a,len(a),split)
            oos=[t for t in oos if t["signal_date"]>=a[split]["date"]]
            # Full-period results retained for context; train and OOS separated chronologically.
            meta={"ticker":ticker,"bars":len(a),"from":a[0]["date"],"to":a[-1]["date"],
                  "train":stats(train),"out_of_sample":stats(oos)}
            per.append(meta);all_trades.extend(oos);all_rows.extend(train+oos)
            print(f"{ticker}: {len(a)} candles; train {len(train)}; OOS {len(oos)}")
        except Exception as e:
            per.append({"ticker":ticker,"status":"download_or_parse_error","error":str(e)})
            print(f"{ticker}: ERROR {e}")
    result={"method":"Prosperity v3.8 corrected EMA, RSI reversal rule, volume and resistance filters; daily-core walk-forward; chronological 70/30 split; next-session limit entry; 10-session expiry; 20-session exit; gap-aware conservative fills; stop-first on same-bar stop/target; 0.05% fee each side",
      "scope_note":"This is a test of the daily core only. The Android 50/30/20 multi-timeframe score uses hourly and 10-minute candles, whose historical availability on MOEX is not sufficient for a comparable multi-year test. Do not treat these results as validation of the full multi-timeframe model.",
      "period_from":FROM,"period_to":TODAY,"oos_fraction":OOS_FRACTION,"per_ticker":per,
      "combined_oos":stats(all_trades)}
    with open("backtest-summary.json","w",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    with open("backtest-trades.csv","w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(all_rows[0].keys()) if all_rows else ["ticker"]);w.writeheader();w.writerows(all_rows)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not all_trades:raise SystemExit("No OOS trades were produced; inspect data/API availability.")

if __name__=="__main__":main()
