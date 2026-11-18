"""محفظة تداول ورقية محلية فقط؛ لا تحتوي اتصالاً لتنفيذ أوامر حقيقية."""
import json, uuid, threading
from pathlib import Path
from datetime import datetime, timezone
from tools import market_tools
STORE=Path(__file__).resolve().parent/"data"/"paper_account.json"
LOCK=threading.RLock(); DEFAULT_EQUITY=10000.0; MAX_RISK_PCT=1.0

def _default(): return {"initial_equity":DEFAULT_EQUITY,"cash":DEFAULT_EQUITY,"realized_pnl":0.0,"positions":[],"closed_trades":[],"updated":datetime.now(timezone.utc).isoformat()}
def load():
    with LOCK:
        try:
            d=json.loads(STORE.read_text(encoding="utf-8"))
            if not isinstance(d,dict) or not isinstance(d.get("positions"),list): raise ValueError()
            return d
        except (OSError,ValueError,json.JSONDecodeError): return _default()
def save(d):
    with LOCK:
        STORE.parent.mkdir(parents=True,exist_ok=True); tmp=STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(STORE)
def snapshot(refresh=False):
    d=load(); unreal=0.0; auto_close=[]
    for p in list(d["positions"]):
        if refresh:
            try:
                q,_=market_tools.quote(p["symbol"])
                if q is not None:
                    p["mark_price"]=float(q)
                    if p["side"]=="LONG" and q<=p["stop"]: auto_close.append((p["id"],p["stop"],"STOP"))
                    elif p["side"]=="LONG" and q>=p["target"]: auto_close.append((p["id"],p["target"],"TARGET"))
                    elif p["side"]=="SHORT" and q>=p["stop"]: auto_close.append((p["id"],p["stop"],"STOP"))
                    elif p["side"]=="SHORT" and q<=p["target"]: auto_close.append((p["id"],p["target"],"TARGET"))
            except Exception: pass
        mark=float(p.get("mark_price",p["entry"]))
        p["unrealized_pnl"]=(mark-p["entry"])*p["qty"]*(1 if p["side"]=="LONG" else -1)
        unreal+=p["unrealized_pnl"]
    if refresh:
        save(d)
        for pid, price, reason in auto_close:
            try: close_position(pid, price, reason)
            except ValueError: pass
        d=load(); unreal=sum(float(p.get("unrealized_pnl",0)) for p in d["positions"])
    return {"mode":"PAPER_ONLY","initial_equity":d["initial_equity"],"cash":round(d["cash"],2),"realized_pnl":round(d["realized_pnl"],2),"unrealized_pnl":round(unreal,2),"equity":round(float(d["cash"])+unreal,2),"positions":d["positions"],"closed_trades":d["closed_trades"][-50:],"max_risk_pct":MAX_RISK_PCT}
def open_position(symbol,side,entry,stop,target,risk_pct=.5):
    side=str(side).upper(); entry,stop,target,risk_pct=map(float,(entry,stop,target,risk_pct))
    if side not in ("LONG","SHORT"): raise ValueError("الاتجاه يجب أن يكون LONG أو SHORT")
    if min(entry,stop,target)<=0 or not 0<risk_pct<=MAX_RISK_PCT: raise ValueError("أسعار أو مخاطرة غير صالحة؛ الحد الأقصى للمخاطرة 1%")
    if (side=="LONG" and not stop<entry<target) or (side=="SHORT" and not target<entry<stop): raise ValueError("ترتيب الدخول والوقف والهدف غير صحيح")
    with LOCK:
        d=load()
        if any(p["symbol"]==symbol for p in d["positions"]): raise ValueError("يوجد مركز مفتوح بالفعل على هذا الأصل")
        equity=float(d["cash"])+sum(float(p.get("unrealized_pnl",0)) for p in d["positions"])
        used_exposure=sum(float(p.get("notional",0)) for p in d["positions"])
        available_exposure=max(0.0,equity-used_exposure)
        if available_exposure <= 0: raise ValueError("لا توجد قدرة تعرض متاحة في المحفظة الورقية")
        risk_cash=equity*risk_pct/100; qty=risk_cash/abs(entry-stop); notional=qty*entry
        if notional>available_exposure: qty=available_exposure/entry; notional=qty*entry; risk_cash=qty*abs(entry-stop)
        p={"id":uuid.uuid4().hex[:10],"symbol":symbol,"side":side,"entry":entry,"mark_price":entry,"stop":stop,"target":target,"qty":qty,"notional":notional,"risk_cash":risk_cash,"risk_pct":risk_pct,"unrealized_pnl":0.0,"opened_at":datetime.now(timezone.utc).isoformat(),"status":"OPEN"}
        d["positions"].append(p); save(d); return p
def close_position(position_id,exit_price=None,reason="MANUAL"):
    with LOCK:
        d=load(); p=next((x for x in d["positions"] if x["id"]==position_id),None)
        if not p: raise ValueError("المركز غير موجود")
        if exit_price is None: exit_price,_=market_tools.quote(p["symbol"])
        if exit_price is None or float(exit_price)<=0: raise ValueError("تعذر الحصول على سعر خروج صالح")
        exit_price=float(exit_price); pnl=(exit_price-p["entry"])*p["qty"]*(1 if p["side"]=="LONG" else -1)
        p.update(exit_price=exit_price,realized_pnl=round(pnl,8),closed_at=datetime.now(timezone.utc).isoformat(),reason=reason,status="CLOSED")
        d["cash"]+=pnl; d["realized_pnl"]+=pnl; d["positions"].remove(p); d["closed_trades"].append(p); save(d); return p
def reset():
    with LOCK: save(_default())
    return snapshot()
