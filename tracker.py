"""سجل القرارات + متابعة نتيجتها الفعلية (هل ضُرب الهدف أم الوقف؟) للشراء والبيع."""
import json, time, uuid
from datetime import datetime
from pathlib import Path
from tools import market_tools as m

HIST = Path(__file__).resolve().parent / "data" / "history.json"


def load():
    try:
        return json.loads(HIST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def save(h):
    HIST.parent.mkdir(exist_ok=True)
    HIST.write_text(json.dumps(h[:300], ensure_ascii=False, indent=1), encoding="utf-8")


def make_entry(symbol, capital, mode, result):
    p = result.get("plan")
    ok = p and (result["decision"] == "APPROVED" or result.get("grade") in ("A", "B"))
    return {"id": uuid.uuid4().hex[:8], "time": datetime.now().isoformat(timespec="seconds"), "ts": int(time.time() * 1000),
            "symbol": symbol, "capital": capital, "mode": mode, "style": result.get("mode"), "action": result.get("action"),
            "decision": result["decision"], "plan": p, "report": result["report"], "grade": result.get("grade"),
            "regime_label": result.get("regime_label"), "confidence": result.get("confidence"),
            "status": "open" if ok else "na", "r": None}


def add(entry):
    h = load()
    h.insert(0, entry)
    save(h)


def _resolve(e):
    p = e["plan"]
    sd = 1 if p.get("action", "BUY") == "BUY" else -1
    try:
        raw = m.history_since(e["symbol"], e["ts"], p.get("track", "1h"))
    except Exception:  # noqa: BLE001
        return
    risk = abs(p["entry"] - p["stop_loss"]) or 1e-9
    for _ts, _o, hi, lo, cl, _v in raw:
        sl_hit = lo <= p["stop_loss"] if sd > 0 else hi >= p["stop_loss"]
        tp_hit = hi >= p["take_profit"] if sd > 0 else lo <= p["take_profit"]
        if sl_hit:                          # إذا لمس الاثنان في نفس الشمعة نفترض الوقف أولاً (تحفظ)
            e["status"], e["r"] = "sl", -1.0
            return
        if tp_hit:
            e["status"], e["r"] = "tp", round(abs(p["take_profit"] - p["entry"]) / risk, 2)
            return
    if time.time() * 1000 - e["ts"] > p.get("expire_ms", 14 * 86400 * 1000):
        last = raw[-1][4] if raw else p["entry"]
        e["status"], e["r"] = "expired", round(sd * (last - p["entry"]) / risk, 2)


def refresh():
    h = load()
    for e in h:
        if e.get("status") == "open" and e.get("plan"):
            _resolve(e)
    save(h)


def stats(h):
    ap = [e for e in h if e.get("plan") and e.get("status") != "na"]
    tp = sum(e.get("status") == "tp" for e in ap)
    sl = sum(e.get("status") == "sl" for e in ap)
    ex = sum(e.get("status") == "expired" for e in ap)
    rs = [e["r"] for e in ap if e.get("r") is not None]
    return {"approved": len(ap), "open": sum(e.get("status") == "open" for e in ap), "tp": tp, "sl": sl, "expired": ex,
            "win_rate": round(100 * tp / (tp + sl), 1) if tp + sl else None,
            "avg_r": round(sum(rs) / len(rs), 2) if rs else None, "resolved": len(rs)}
