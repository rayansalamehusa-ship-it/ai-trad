"""MetaTrader 5 Demo bridge. Strictly refuses real accounts; no credential storage."""
import json, os, threading
from pathlib import Path

BASE = Path(__file__).resolve().parent
SETTINGS = BASE / "data" / "mt5_settings.json"
LOCK = threading.RLock()
MAGIC = 6182026


def _mt5():
    try:
        import MetaTrader5 as mt5
        return mt5, None
    except Exception as exc:
        return None, f"حزمة MetaTrader5 غير مثبتة أو غير مدعومة على هذا النظام: {exc}"


def _settings():
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return {"auto_trade": bool(d.get("auto_trade", False)), "risk_pct": float(d.get("risk_pct", 0.5))}
    except Exception:
        return {"auto_trade": False, "risk_pct": 0.5}


def set_auto(enabled, risk_pct=None):
    with LOCK:
        old = _settings()
        risk = float(risk_pct if risk_pct is not None else old["risk_pct"])
        if not 0.1 <= risk <= 1.0:
            raise ValueError("المخاطرة يجب أن تكون بين 0.1% و1% كحد أقصى")
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps({"auto_trade": bool(enabled), "risk_pct": risk}, indent=2), encoding="utf-8")
        return _settings()


def _account(mt5):
    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"لا يوجد حساب مسجل في منصة MT5: {mt5.last_error()}")
    # MT5 ACCOUNT_TRADE_MODE_DEMO = 0. Reject contest/real explicitly.
    if int(info.trade_mode) != int(mt5.ACCOUNT_TRADE_MODE_DEMO):
        raise PermissionError("مرفوض: الحساب الحالي ليس حساب Demo. لن يتم إرسال أي أمر.")
    if not bool(getattr(info, "trade_allowed", True)):
        raise PermissionError("التداول غير مسموح لهذا الحساب أو الطرفية")
    return info


def connect():
    mt5, err = _mt5()
    if err:
        return {"connected": False, "demo": False, "error": err, "settings": _settings()}
    with LOCK:
        if not mt5.initialize():
            return {"connected": False, "demo": False, "error": f"تعذر تشغيل/الاتصال بالطرفية: {mt5.last_error()}", "settings": _settings()}
        try:
            a = _account(mt5)
            return {"connected": True, "demo": True, "login": int(a.login), "server": str(a.server),
                    "currency": str(a.currency), "balance": float(a.balance), "equity": float(a.equity),
                    "settings": _settings()}
        except Exception as exc:
            return {"connected": False, "demo": False, "error": str(exc), "settings": _settings()}


def status():
    result = connect()
    result["settings"] = _settings()
    return result


def performance(days=90):
    """Read-only Demo performance for this app's magic-number deals only."""
    mt5, err = _mt5()
    if err:
        return {"available": False, "error": err}
    if not mt5.initialize():
        return {"available": False, "error": f"تعذر الاتصال بـ MT5: {mt5.last_error()}"}
    try:
        account = _account(mt5)
        from datetime import datetime, timedelta
        start, end = datetime.now() - timedelta(days=max(1, min(int(days), 365))), datetime.now()
        deals = list(mt5.history_deals_get(start, end) or [])
        bot_deals = [d for d in deals if int(getattr(d, "magic", 0)) == MAGIC]
        active_positions = [p for p in list(mt5.positions_get() or []) if int(getattr(p, "magic", 0)) == MAGIC]
        active_ids = {int(getattr(p, "identifier", 0) or 0) for p in active_positions}
        grouped = {}
        for d in bot_deals:
            pid = int(getattr(d, "position_id", 0) or 0)
            if not pid:
                continue
            row = grouped.setdefault(pid, {"position_id": pid, "symbol": str(d.symbol), "pnl": 0.0, "commission": 0.0, "swap": 0.0, "fee": 0.0, "time": int(d.time)})
            row["pnl"] += float(getattr(d, "profit", 0) or 0)
            row["commission"] += float(getattr(d, "commission", 0) or 0)
            row["swap"] += float(getattr(d, "swap", 0) or 0)
            row["fee"] += float(getattr(d, "fee", 0) or 0)
            row["time"] = max(row["time"], int(d.time))
        closed = []
        out_entries = {getattr(mt5, "DEAL_ENTRY_OUT", 1), getattr(mt5, "DEAL_ENTRY_OUT_BY", 3), getattr(mt5, "DEAL_ENTRY_INOUT", 2)}
        closed_ids = {int(d.position_id) for d in bot_deals if int(getattr(d, "entry", -1)) in out_entries and int(getattr(d, "position_id", 0) or 0)}
        for pid in closed_ids - active_ids:
            row = grouped.get(pid)
            if row:
                row["net_pnl"] = round(row["pnl"] + row["commission"] + row["swap"] + row["fee"], 2)
                closed.append(row)
        wins = [x for x in closed if x["net_pnl"] > 0]
        losses = [x for x in closed if x["net_pnl"] < 0]
        positions = []
        for p in active_positions:
            if int(getattr(p, "magic", 0)) == MAGIC:
                positions.append({"ticket": int(p.ticket), "symbol": str(p.symbol), "type": int(p.type), "volume": float(p.volume),
                                  "price_open": float(p.price_open), "price_current": float(p.price_current), "sl": float(p.sl),
                                  "tp": float(p.tp), "profit": float(p.profit), "swap": float(p.swap)})
        return {"available": True, "demo": True, "server": str(account.server), "currency": str(account.currency),
                "balance": float(account.balance), "equity": float(account.equity), "open_positions": positions,
                "closed_trades": sorted(closed, key=lambda x: x["time"], reverse=True)[:100],
                "trades": len(closed), "wins": len(wins), "losses": len(losses),
                "win_rate": round(100 * len(wins) / len(closed), 1) if closed else None,
                "net_pnl": round(sum(x["net_pnl"] for x in closed), 2),
                "avg_win": round(sum(x["net_pnl"] for x in wins) / len(wins), 2) if wins else None,
                "avg_loss": round(sum(x["net_pnl"] for x in losses) / len(losses), 2) if losses else None,
                "period_days": max(1, min(int(days), 365)), "scope": "صفقات التطبيق فقط (magic number)"}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _symbol(mt5, raw):
    mapping = {}
    for pair in (os.getenv("MT5_SYMBOL_MAP", "") or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1); mapping[k.strip().upper()] = v.strip()
    key = str(raw).upper().replace(" ", "")
    candidates = [mapping[key]] if key in mapping else []
    compact = key.replace("/", "")
    candidates += [compact, compact.replace("USDT", "USD")]
    for name in dict.fromkeys(x for x in candidates if x):
        info = mt5.symbol_info(name)
        if info is not None:
            if not info.visible and not mt5.symbol_select(name, True):
                continue
            return name, mt5.symbol_info_tick(name), info
    raise ValueError(f"رمز {raw} غير موجود لدى وسيط MT5. أضفه إلى Market Watch أو عيّن MT5_SYMBOL_MAP في .env")


def _volume_for_risk(mt5, symbol, side, price, stop, equity, risk_pct, info):
    risk_cash = equity * risk_pct / 100.0
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    loss = mt5.order_calc_profit(order_type, symbol, 1.0, price, stop)
    if loss is None or abs(float(loss)) <= 0:
        raise ValueError("تعذر حساب خسارة اللوت عند وقف الخسارة لهذا الرمز")
    raw = risk_cash / abs(float(loss))
    step = float(info.volume_step or 0.01)
    vmin, vmax = float(info.volume_min), float(info.volume_max)
    volume = min(vmax, (int(raw / step + 1e-9)) * step)
    if volume < vmin:
        raise ValueError(f"حجم العقد المحسوب ({raw:.4f}) أقل من الحد الأدنى للوسيط ({vmin})؛ لن نرفع المخاطرة تلقائياً")
    volume = round(volume, 8)
    actual_loss = abs(float(mt5.order_calc_profit(order_type, symbol, volume, price, stop) or 0))
    if actual_loss > risk_cash * 1.005:
        raise ValueError("حجم العقد يتجاوز حد المخاطرة بعد التقريب؛ تم إلغاء الأمر")
    return volume, risk_cash, actual_loss


def execute_signal(plan, risk_pct=None):
    """Send one approved signal at current Bid/Ask, only to a verified Demo account."""
    mt5, err = _mt5()
    if err:
        return {"ok": False, "error": err}
    with LOCK:
        if not mt5.initialize():
            return {"ok": False, "error": f"تعذر الاتصال بـ MT5: {mt5.last_error()}"}
        try:
            account = _account(mt5)  # Re-check immediately before every order.
            if not isinstance(plan, dict) or plan.get("action") not in ("BUY", "SELL"):
                raise ValueError("لا توجد إشارة صالحة للتنفيذ")
            symbol, tick, info = _symbol(mt5, plan.get("symbol", ""))
            if tick is None:
                raise RuntimeError("لا يوجد سعر حي للرمز في MT5")
            side = plan["action"]
            price = float(tick.ask if side == "BUY" else tick.bid)
            stop, target = float(plan["stop_loss"]), float(plan["take_profit"])
            if price <= 0 or stop <= 0 or target <= 0:
                raise ValueError("سعر السوق أو مستويات الوقف/الهدف غير صالحة")
            if side == "BUY" and not stop < price < target:
                raise ValueError("الإشارة لم تعد صالحة عند السعر الحالي؛ السعر تجاوز مستوى الدخول/الهدف أو اقترب من الوقف")
            if side == "SELL" and not target < price < stop:
                raise ValueError("الإشارة لم تعد صالحة عند السعر الحالي؛ لن نطارد السعر")
            live_rr = abs(target - price) / max(abs(price - stop), 1e-12)
            required_rr = max(1.0, float(plan.get("rr", 1.0)) * 0.65)
            if live_rr < required_rr:
                raise ValueError(f"تم رفض الدخول المتأخر: العائد/المخاطرة عند السعر الحالي {live_rr:.2f} أقل من الحد {required_rr:.2f}")
            min_stop = float(getattr(info, "trade_stops_level", 0) or 0) * float(info.point or 0)
            if min_stop and (abs(price - stop) < min_stop or abs(target - price) < min_stop):
                raise ValueError("مسافة وقف الخسارة أو الهدف أقل من الحد الأدنى الذي يفرضه الوسيط")
            risk = float(risk_pct if risk_pct is not None else _settings()["risk_pct"])
            if not 0.1 <= risk <= 1.0:
                raise ValueError("حد المخاطرة المسموح 0.1% إلى 1%")
            volume, risk_cash, actual_loss = _volume_for_risk(mt5, symbol, side, price, stop, float(account.equity), risk, info)
            # Prevent duplicate bot positions and cap aggregate bot risk at 2% equity.
            open_positions = list(mt5.positions_get() or [])
            bot_positions = [p for p in open_positions if int(getattr(p, "magic", 0)) == MAGIC]
            if any(str(p.symbol) == symbol for p in bot_positions):
                raise ValueError("يوجد مركز مفتوح من التطبيق على هذا الرمز؛ تم منع تكرار الدخول")
            if len(bot_positions) >= 3:
                raise ValueError("تم بلوغ الحد الأقصى: 3 مراكز Demo مفتوحة")
            existing_risk = 0.0
            for pos in bot_positions:
                if not float(getattr(pos, "sl", 0) or 0):
                    raise ValueError("يوجد مركز آلي مفتوح بلا وقف خسارة؛ أوقفنا الدخول الجديد لحماية الحساب")
                pos_type = mt5.ORDER_TYPE_BUY if int(pos.type) == int(mt5.POSITION_TYPE_BUY) else mt5.ORDER_TYPE_SELL
                mark = float(mt5.symbol_info_tick(pos.symbol).bid if pos_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(pos.symbol).ask)
                loss = mt5.order_calc_profit(pos_type, pos.symbol, float(pos.volume), mark, float(pos.sl))
                if loss is not None:
                    existing_risk += abs(float(loss))
            if existing_risk + actual_loss > float(account.equity) * 0.02:
                raise ValueError("إجمالي المخاطرة المفتوحة سيتجاوز 2% من Equity؛ تم رفض الصفقة")
            order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
            fill_flags = int(getattr(info, "filling_mode", 0) or 0)
            if fill_flags & int(getattr(mt5, "SYMBOL_FILLING_IOC", 2)):
                filling = mt5.ORDER_FILLING_IOC
            elif fill_flags & int(getattr(mt5, "SYMBOL_FILLING_FOK", 1)):
                filling = mt5.ORDER_FILLING_FOK
            elif int(getattr(info, "trade_exemode", -1)) != int(getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", 2)):
                filling = mt5.ORDER_FILLING_RETURN
            else:
                raise ValueError("نوع تنفيذ الأوامر المتاح لدى الوسيط غير مدعوم بأمان")
            request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
                       "type": order_type, "price": price, "sl": round(stop, int(info.digits)),
                       "tp": round(target, int(info.digits)), "deviation": 20, "magic": MAGIC,
                       "comment": "AI-Demo-Only", "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling}
            result = mt5.order_send(request)
            if result is None:
                raise RuntimeError(f"لم يرجع MT5 نتيجة للأمر: {mt5.last_error()}")
            accepted = {mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -1), getattr(mt5, "TRADE_RETCODE_PLACED", -2)}
            if int(result.retcode) not in accepted:
                raise RuntimeError(f"رفض وسيط Demo الأمر: retcode={result.retcode}, comment={getattr(result, 'comment', '')}")
            return {"ok": True, "demo": True, "symbol": symbol, "side": side,
                    "requested_price": price, "volume": float(getattr(result, "volume", volume) or volume), "stop_loss": stop, "take_profit": target,
                    "risk_cash_estimate": round(actual_loss, 2), "risk_budget": round(risk_cash, 2),
                    "order": int(getattr(result, "order", 0) or 0), "deal": int(getattr(result, "deal", 0) or 0),
                    "retcode": int(result.retcode), "message": "تم إرسال الأمر إلى حساب Demo فقط"}
        except Exception as exc:
            return {"ok": False, "demo": False, "error": str(exc)}


def maybe_execute(result):
    cfg = _settings()
    if not cfg["auto_trade"]:
        return None
    if not isinstance(result, dict) or result.get("decision") != "APPROVED" or not result.get("plan"):
        return {"ok": False, "skipped": True, "reason": "الإشارة لم تجتز شروط الاعتماد الصارم"}
    return execute_signal(result["plan"], cfg["risk_pct"])
