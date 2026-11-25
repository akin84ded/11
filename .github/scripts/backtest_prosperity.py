#!/usr/bin/env python3
"""Walk-forward test of the exact Prosperity v3.7 daily scoring rules.
No future data is used to create a signal. Trades enter no earlier than the next session.
"""
import csv, json, math, os, time
from datetime import date, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

TICKERS = os.getenv("TICKERS", "SBER,GAZP,LKOH,ROSN,NVTK").split(",")
FROM = os.getenv("FROM_DATE", "2021-01-01")
HORIZON = int(os.getenv("HORIZON", "20"))
ENTRY_DAYS = int(os.getenv("ENTRY_DAYS", "10"))
FEE_SIDE = float(os.getenv("FEE_SIDE", "0.0005"))  # 0.05% per side
TODAY = date.today().isoformat()

def get_json(url):
    last = None
    for attempt in range(3):
        for scheme in ("https", "http"):
            try:
                req = Request(url.replace("https://", scheme+"://"), headers={"User-Agent":"Prosperity-backtest/1.0"})
                with urlopen(req, timeout=25) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                last = e
        time.sleep(1.5*(attempt+1))
    raise RuntimeError(f"MOEX request failed: {last}")

def load(ticker):
    out=[]
    start=0
    while True:
        url=(f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
             f"?from={FROM}&till={TODAY}&interval=24&start={start}&iss.meta=off")
        obj=get_json(url)
        block=obj.get("candles",{})
        cols=block.get("columns",[])
        rows=block.get("data",[])
        if not rows: break
        ix={k:i for i,k in enumerate(cols)}
        for r in rows:
            try:
                c={"date":str(r[ix["begin"]])[:10],"open":float(r[ix["open"]]),"high":float(r[ix["high"]]),
                   "low":float(r[ix["low"]]),"close":float(r[ix["close"]]),"volume":float(r[ix["volume"]])}
                if c["close"]>0: out.append(c)
            except (KeyError,IndexError,TypeError,ValueError): pass
        start += len(rows)
        if len(rows)<500: break
        if start>20000: break
    # de-duplicate and sort
    d={x["date"]:x for x in out}
    return [d[k] for k in sorted(d)]

def sma(a,end,p):
    if end<p: return float("nan")
    return sum(x["close"] for x in a[end-p:end])/p

# Deliberately mirrors the Java implementation, including its current EMA initialization behavior.
def ema_java(a,end,p):
    if end<p: return float("nan")
    v=sum(x["close"] for x in a[end-p:end])/p
    k=2.0/(p+1)
    for i in range(end,len(a)): v=a[i]["close"]*k+v*(1-k)
    return v

def rsi(a,period):
    if len(a)<=period:return float("nan")
    up=dn=0.0
    for i in range(1,period+1):
        d=a[i]["close"]-a[i-1]["close"]
        if d>0:up+=d
        else:dn-=d
    up/=period;dn/=period
    for i in range(period+1,len(a)):
        d=a[i]["close"]-a[i-1]["close"]
        up=(up*(period-1)+max(0,d))/period
        dn=(dn*(period-1)+max(0,-d))/period
    return 100.0 if dn==0 else 100-100/(1+up/dn)

def indicators(a,end):
    p=a[end-1]["close"]
    s20=sma(a,end,20);s50=sma(a,end,50);s200=sma(a,end,200)
    rr=rsi(a[:end],14)
    # Java ema() is called on the complete array with end=n; emulate its values at historical end.
    # For the previous MACD, Java uses ema(a,n-1,p) and therefore folds in candle n-1 once.
    e12=ema_java(a[:end],end,12);e26=ema_java(a[:end],end,26)
    prev12=ema_java(a[:end],end-1,12);prev26=ema_java(a[:end],end-1,26)
    macd=e12-e26; prev=prev12-prev26
    trs=[]
    for i in range(end-14,end):
        x=a[i];pr=a[i-1]
        trs.append(max(x["high"]-x["low"],abs(x["high"]-pr["close"]),abs(x["low"]-pr["close"])))
    atr=sum(trs)/14
    score=0
    score += 1 if p>s20 else -1
    score += 1 if s20>s50 else -1
    if not math.isnan(s200): score += 1 if p>s200 else -1
    score += 1 if macd>prev else -1
    if rr<30: score+=1
    elif rr>70: score-=2
    elif rr>=50: score+=1
    entry=p if p<=s20 else min(s20,p-0.5*atr)
    if entry<=0: entry=p
    return {"score":score,"price":p,"sma20":s20,"sma50":s50,"sma200":s200,"rsi":rr,"atr":atr,
            "macd":macd,"prev_macd":prev,"entry":entry,"stop":max(0,entry-1.5*atr),"target":entry+3*atr}

def backtest(ticker,a):
    if len(a)<260: return [], {"ticker":ticker,"bars":len(a),"status":"insufficient history"}
    trades=[]; i=200
    while i < len(a)-HORIZON-1:
        z=indicators(a,i+1)
        if z["score"]<3:
            i+=1; continue
        # limit entry is placed only after the signal candle has closed
        fill=None
        for j in range(i+1,min(i+1+ENTRY_DAYS,len(a))):
            if a[j]["low"]<=z["entry"]:
                fill=j
                # A limit order filled after a downward gap gets the opening price, not the worse limit.
                actual_entry=min(z["entry"],a[j]["open"])
                break
        if fill is None:
            i+=1;continue
        exit_idx=None;exit_price=None;reason=None
        stop=z["stop"];target=z["target"]
        last=min(len(a)-1,fill+HORIZON)
        for j in range(fill,last+1):
            hit_stop=a[j]["low"]<=stop
            hit_target=a[j]["high"]>=target
            if hit_stop and hit_target:
                exit_idx=j;exit_price=min(stop,a[j]["open"]);reason="both_same_bar_stop_first";break
            if hit_stop:
                exit_idx=j;exit_price=min(stop,a[j]["open"]);reason="stop";break
            if hit_target:
                exit_idx=j;exit_price=max(target,a[j]["open"]);reason="target";break
        if exit_idx is None:
            exit_idx=last;exit_price=a[last]["close"];reason="time_exit"
        entry=actual_entry
        # Keep the model's originally proposed stop/target; gap-aware execution is used for exits.
        gross=exit_price/entry-1
        net=(exit_price*(1-FEE_SIDE))/(entry*(1+FEE_SIDE))-1
        bh=(a[exit_idx]["close"]/a[fill]["open"])-1 if a[fill]["open"] else 0
        trades.append({"ticker":ticker,"signal_date":a[i]["date"],"fill_date":a[fill]["date"],
                       "exit_date":a[exit_idx]["date"],"score":z["score"],"entry":round(entry,4),
                       "stop":round(stop,4),"target":round(target,4),"exit":round(exit_price,4),
                       "reason":reason,"gross_pct":round(gross*100,3),"net_pct":round(net*100,3),
                       "benchmark_pct":round(bh*100,3),"bars_held":exit_idx-fill})
        i=exit_idx+1  # one position at a time per ticker
    return trades, {"ticker":ticker,"bars":len(a),"from":a[0]["date"],"to":a[-1]["date"],"signals_filled":len(trades)}

def stats(trades):
    if not trades:return {"trades":0}
    rs=[x["net_pct"] for x in trades]
    wins=[x for x in rs if x>0]
    losses=[x for x in rs if x<=0]
    gross_profit=sum(x for x in rs if x>0);gross_loss=-sum(x for x in rs if x<0)
    eq=peak=1.0;maxdd=0.0
    for x in rs:
        eq*=1+x/100;peak=max(peak,eq);maxdd=min(maxdd,(eq/peak-1)*100)
    return {"trades":len(rs),"win_rate_pct":round(len(wins)/len(rs)*100,2),
            "avg_net_pct":round(sum(rs)/len(rs),3),"median_net_pct":round(sorted(rs)[len(rs)//2],3),
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
            "max_drawdown_pct":round(maxdd,2),"avg_benchmark_pct":round(sum(x["benchmark_pct"] for x in trades)/len(trades),3),
            "targets":sum(x["reason"]=="target" for x in trades),"stops":sum(x["reason"] in ("stop","both_same_bar_stop_first") for x in trades),
            "time_exits":sum(x["reason"]=="time_exit" for x in trades)}

def main():
    all_trades=[]; per=[]
    for ticker in TICKERS:
        try:
            candles=load(ticker)
            tr,meta=backtest(ticker,candles)
            all_trades.extend(tr);meta.update(stats(tr));per.append(meta)
            print(f"{ticker}: {len(candles)} candles, {len(tr)} trades")
        except Exception as e:
            per.append({"ticker":ticker,"status":"download_or_parse_error","error":str(e)})
            print(f"{ticker}: ERROR {e}")
    result={"method":"Prosperity v3.7 exact daily score; walk-forward; next-session limit entry; 10-session entry expiry; 20-session exit; stop-first if stop and target touch same candle; 0.05% fee each side",
            "period_from":FROM,"period_to":TODAY,"per_ticker":per,"combined":stats(all_trades)}
    with open("backtest-summary.json","w",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    with open("backtest-trades.csv","w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(all_trades[0].keys()) if all_trades else ["ticker"])
        w.writeheader();w.writerows(all_trades)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not all_trades: raise SystemExit("No trades were produced; inspect data/API availability.")

if __name__=="__main__":main()
