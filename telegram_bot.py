"""Telegram remote control for the local AI trading app (PAPER ONLY).

Uses Telegram long polling. Only TELEGRAM_CHAT_ID is authorized. No live-order
API exists here; all portfolio actions call paper_trading directly.
"""
import os
import threading
import time
import traceback
from datetime import datetime

import requests
from dotenv import set_key

import engine
import intelligence
import orderflow
import paper_trading
import tracker
from tools import brain, market_tools
from tools.assets import normalize

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE, ".env")
API = "https://api.telegram.org/bot{}/{}"
_started = False
_start_lock = threading.Lock()
_poll_thread = None
_pending = {}

MENU = [["📊 حالة النظام", "💼 المحفظة"], ["🧠 تحليل أصل", "🌊 تدفق الأوامر"],
        ["📂 المراكز المفتوحة", "📈 سجل الصفقات"], ["▶️ تفعيل المسح", "⏸ إيقاف المسح"],
        ["🧬 حالة التعلم", "❓ المساعدة"]]


def _credentials():
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _api(method, payload=None, timeout=15):
    token, _ = _credentials()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN غير مضبوط")
    response = requests.post(API.format(token, method), json=payload or {}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(str(data.get("description", "Telegram API error")))
    return data.get("result")


def send(chat_id, text, keyboard=True):
    # Telegram messages are limited to 4096 chars; leave room for safety.
    chunks = [text[i:i + 3900] for i in range(0, len(str(text)), 3900)] or [""]
    for chunk in chunks:
        payload = {"chat_id": str(chat_id), "text": chunk}
        if keyboard:
            payload["reply_markup"] = {"keyboard": MENU, "resize_keyboard": True, "is_persistent": True}
        _api("sendMessage", payload)


def _authorized(message):
    _, allowed = _credentials()
    chat = str((message.get("chat") or {}).get("id", ""))
    sender = str((message.get("from") or {}).get("id", ""))
    # Private chats only; require both chat and sender to match configured ID.
    return bool(allowed and chat == allowed and sender == allowed and (message.get("chat") or {}).get("type") == "private")


def _help():
    return ("🤖 لوحة التحكم بالتطبيق — PAPER TRADING فقط\n\n"
            "/status — حالة النظام\n/paper — رصيد المحفظة\n/positions — المراكز المفتوحة\n"
            "/analyze BTC/USDT — تحليل كامل للأصل\n/market BTC/USDT — فهم السوق + التدفق\n/orderflow BTC/USDT — تدفق الصفقات والدفتر\n"
            "/open BTC/USDT LONG ENTRY STOP TARGET [RISK%] — فتح مركز ورقي\n"
            "/close POSITION_ID [EXIT_PRICE] — إغلاق مركز ورقي\n"
            "/scan — فحص قائمة المتابعة وإظهار أفضل نتيجة\n"
            "/auto_on [minutes] — تفعيل تنبيهات المسح (لا تفتح صفقات)\n/auto_off — إيقاف المسح\n"
            "/history — ملخص سجل الصفقات\n/brain — حالة التعلم\n/reset — إعادة ضبط المحفظة بعد إغلاق كل المراكز\n\n"
            "لا يوجد تنفيذ تداول حقيقي عبر هذا البوت.")


def _paper_text(refresh=False):
    a = paper_trading.snapshot(refresh=refresh)
    lines = ["💼 المحفظة الورقية", f"الرصيد النقدي: ${a['cash']:,.2f}",
             f"قيمة المحفظة: ${a['equity']:,.2f}", f"الربح المحقق: ${a['realized_pnl']:,.2f}",
             f"الربح العائم: ${a['unrealized_pnl']:,.2f}", f"المراكز المفتوحة: {len(a['positions'])}",
             f"الصفقات المغلقة المسجلة: {len(a['closed_trades'])}", "الوضع: PAPER ONLY"]
    return "\n".join(lines)


def _positions_text(refresh=False):
    positions = paper_trading.snapshot(refresh=refresh)["positions"]
    if not positions:
        return "لا توجد مراكز ورقية مفتوحة حالياً."
    out = ["📂 المراكز المفتوحة"]
    for p in positions:
        out.append(f"{p['symbol']} · {p['side']}\nID: {p['id']}\nالدخول: {p['entry']} | السعر: {p.get('mark_price', p['entry'])}\nوقف: {p['stop']} | هدف: {p['target']}\nP&L عائم: ${p.get('unrealized_pnl', 0):.2f}")
    return "\n\n".join(out)


def _status_text():
    auto = int(float(os.getenv("AUTO_SCAN_MIN", "0") or 0))
    return ("🖥 حالة النظام\nالحالة: متصل\nوضع التنفيذ: PAPER ONLY\n"
            f"المسح الدوري: {'مفعّل كل ' + str(auto) + ' دقيقة' if auto else 'متوقف'}\n"
            f"قائمة المتابعة: {os.getenv('WATCHLIST', 'BTC,ETH,SOL')}\n"
            f"محركات التحليل: Market Intelligence + Order Flow + Paper Trading + Adaptive Brain")


def _run_analysis(chat_id, symbol):
    try:
        send(chat_id, f"⏳ بدأت عملية التحليل لـ {symbol}. سأرسل النتيجة عند اكتمالها.")
        result = engine.run_analysis(symbol, float(os.getenv("AUTO_CAPITAL", "1000") or 1000), "local", "swing", lambda *args: None)
        tracker.add(tracker.make_entry(symbol, float(os.getenv("AUTO_CAPITAL", "1000") or 1000), "telegram", result))
        decision = result.get("decision", "غير متاح")
        msg = f"🧠 نتيجة تحليل {symbol}\nالقرار: {decision}\nقوة الشراء: {result.get('buy_pct', '—')}% | البيع: {result.get('sell_pct', '—')}%"
        plan = result.get("plan")
        if plan:
            msg += (f"\nالاتجاه: {plan.get('action')}\nالدخول: {plan.get('entry')}\n"
                    f"وقف الخسارة: {plan.get('stop_loss')}\nالهدف 1: {plan.get('take_profit')}\n"
                    f"الهدف 2: {plan.get('take_profit2')}\nالتقييم: {plan.get('grade')} ({plan.get('score')}/100)")
        msg += "\n\nهذه نتيجة تحليل فقط؛ لم يتم فتح صفقة تلقائياً."
        send(chat_id, msg)
    except Exception as exc:  # noqa: BLE001
        send(chat_id, f"تعذر إكمال التحليل: {str(exc)[:500]}")


def _handle(chat_id, raw):
    text = (raw or "").strip()
    pending = _pending.pop(str(chat_id), None)
    if pending and text and not text.startswith("/"):
        text = pending + " " + text
    if text in ("❓ المساعدة", "/help", "/start"):
        send(chat_id, "أهلاً بك في بوت التحكم بالتطبيق.\n\n" + _help()); return
    if text in ("📊 حالة النظام", "/status"):
        send(chat_id, _status_text()); return
    if text in ("💼 المحفظة", "/paper"):
        send(chat_id, _paper_text(refresh=True)); return
    if text in ("📂 المراكز المفتوحة", "/positions"):
        send(chat_id, _positions_text(refresh=True)); return
    if text in ("📈 سجل الصفقات", "/history"):
        h = tracker.load(); s = tracker.stats(h)
        send(chat_id, f"📈 سجل الصفقات\nعدد السجلات: {len(h)}\nالإحصاءات: {s}"); return
    if text in ("🧬 حالة التعلم", "/brain"):
        send(chat_id, f"🧬 حالة عقل التطبيق\n{brain.summary()}"); return
    if text in ("▶️ تفعيل المسح", "تفعيل المسح", "تفعيل", "/auto_on") or text.startswith("/auto_on "):
        parts = text.split()
        minutes = 15
        if text not in ("▶️ تفعيل المسح", "تفعيل المسح", "تفعيل", "/auto_on") and len(parts) > 1:
            candidate = parts[1].strip()
            if candidate.isdigit():
                minutes = int(candidate)
            elif candidate.lower() in ("تفعيل", "on", "enable", "enabled"):
                minutes = 15
            else:
                send(chat_id, "صيغة غير صحيحة. استخدم /auto_on أو /auto_on 15 (من 5 إلى 1440 دقيقة).")
                return
        if not 5 <= minutes <= 1440:
            send(chat_id, "حدد فترة بين 5 و1440 دقيقة.")
            return
        os.environ["AUTO_SCAN_MIN"] = str(minutes)
        set_key(ENV_FILE, "AUTO_SCAN_MIN", str(minutes))
        send(chat_id, f"✅ تم تفعيل المسح كل {minutes} دقيقة. هذا يولّد تنبيهات فقط ولا يفتح صفقات.")
        return
    if text in ("⏸ إيقاف المسح", "/auto_off"):
        os.environ["AUTO_SCAN_MIN"] = "0"; set_key(ENV_FILE, "AUTO_SCAN_MIN", "0")
        send(chat_id, "⏸ تم إيقاف المسح الدوري."); return
    if text.startswith("/analyze ") or text == "🧠 تحليل أصل":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            _pending[str(chat_id)] = "/analyze"
            send(chat_id, "أرسل رمز الأصل الذي تريد تحليله، مثال: BTC/USDT"); return
        symbol = normalize(parts[1])
        threading.Thread(target=_run_analysis, args=(chat_id, symbol), daemon=True).start(); return
    if text.startswith("/market "):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send(chat_id, "أرسل الرمز هكذا: /market BTC/USDT"); return
        symbol = normalize(parts[1])
        try:
            frames, errors = {}, {}
            for tf in ("1h", "15m", "5m"):
                try:
                    _source, df = market_tools.candles(symbol, tf, limit=500)
                    frames[tf] = intelligence.analyze_frame(df, tf)
                except Exception as exc: errors[tf] = str(exc)[:100]
            synthesis = intelligence.combine(frames) if frames else {}
            flow = orderflow.analyze(symbol)
            send(chat_id, f"📊 فهم السوق — {symbol}\nالسياق: {synthesis}\nOrder Flow: CVD {flow.get('cvd_notional')} | اختلال الدفتر {flow.get('book_imbalance')}\nالفريمات غير المتاحة: {errors or 'لا يوجد'}\nالمخرجات احتمالية وليست توصية مؤكدة.")
        except Exception as exc: send(chat_id, f"تعذر تحليل السوق: {str(exc)[:400]}")
        return
    if text.startswith("/orderflow ") or text == "🌊 تدفق الأوامر":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            _pending[str(chat_id)] = "/orderflow"
            send(chat_id, "أرسل رمز الأصل لتحليل تدفق الأوامر، مثال: BTC/USDT"); return
        symbol = normalize(parts[1])
        try:
            d = orderflow.analyze(symbol)
            send(chat_id, f"🌊 Order Flow — {symbol}\nمتاح: {d.get('available')}\nCVD: {d.get('cvd_notional')}\nاختلال دفتر الأوامر: {d.get('book_imbalance')}\nالسبريد: {d.get('spread_bps')}\nامتصاص محتمل: {d.get('absorption_possible')}\nملاحظة: بيانات العينة ومؤشرات تقديرية وليست دليلاً قطعياً.")
        except Exception as exc: send(chat_id, f"فشل تحليل التدفق: {str(exc)[:400]}")
        return
    if text.startswith("/open "):
        p = text.split()
        if len(p) not in (6, 7):
            send(chat_id, "الصيغة: /open BTC/USDT LONG ENTRY STOP TARGET [RISK%]"); return
        try:
            pos = paper_trading.open_position(normalize(p[1]), p[2], float(p[3]), float(p[4]), float(p[5]), float(p[6]) if len(p) == 7 else .5)
            send(chat_id, f"✅ فُتح مركز ورقي\n{pos['symbol']} {pos['side']}\nID: {pos['id']}\nالدخول: {pos['entry']}\nوقف: {pos['stop']} | هدف: {pos['target']}\nالحجم: {pos['qty']:.6f}\nلا يوجد تنفيذ حقيقي.")
        except Exception as exc: send(chat_id, f"لم يتم فتح المركز: {str(exc)[:400]}")
        return
    if text.startswith("/close "):
        p = text.split()
        if len(p) not in (2, 3): send(chat_id, "الصيغة: /close POSITION_ID [EXIT_PRICE]"); return
        try:
            trade = paper_trading.close_position(p[1], float(p[2]) if len(p) == 3 else None, "TELEGRAM")
            send(chat_id, f"✅ أُغلق المركز الورقي {trade['symbol']}\nP&L: ${trade['realized_pnl']:.2f}\nسبب الإغلاق: Telegram")
        except Exception as exc: send(chat_id, f"تعذر الإغلاق: {str(exc)[:400]}")
        return
    if text == "/reset":
        try:
            if paper_trading.load().get("positions"):
                send(chat_id, "لا يمكن إعادة الضبط مع وجود مراكز مفتوحة. أغلقها أولاً باستخدام /close."); return
            send(chat_id, "تمت إعادة ضبط المحفظة الورقية.\n" + str(paper_trading.reset()))
        except Exception as exc: send(chat_id, f"تعذر إعادة الضبط: {str(exc)[:300]}")
        return
    if text == "/scan":
        send(chat_id, "⏳ أفحص قائمة المتابعة...")
        def scan_job():
            try:
                symbols = [normalize(x) for x in (os.getenv("WATCHLIST", "BTC,ETH,SOL")).split(",") if x.strip()]
                rows = []
                for sym in symbols[:15]:
                    try:
                        r = engine.analyze(sym, float(os.getenv("AUTO_CAPITAL", "1000") or 1000), "swing", light=True)
                        rows.append((sym, r.get("decision"), r.get("buy_pct"), r.get("sell_pct"), r.get("plan")))
                    except Exception: continue
                rows.sort(key=lambda x: max(float(x[2] or 0), float(x[3] or 0)), reverse=True)
                lines = ["📊 نتائج الفحص (تحليل فقط):"]
                for sym, dec, buy, sell, plan in rows[:8]: lines.append(f"{sym}: {dec} | شراء {buy}% / بيع {sell}%" + (f" | {plan.get('action')}" if plan else ""))
                send(chat_id, "\n".join(lines) if rows else "لم تتوفر نتائج من مصادر السوق.")
            except Exception as exc: send(chat_id, f"تعذر الفحص: {str(exc)[:300]}")
        threading.Thread(target=scan_job, daemon=True).start(); return
    send(chat_id, "لم أفهم الأمر. أرسل /help لعرض الأوامر.")


def _poll():
    offset = None
    while True:
        token, allowed = _credentials()
        if not token or not allowed:
            time.sleep(10); continue
        try:
            updates = _api("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]}, timeout=35) or []
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message") or {}
                if not _authorized(message):
                    # Do not disclose anything to unauthorized chats.
                    continue
                try: _handle(str(message["chat"]["id"]), message.get("text", ""))
                except Exception as exc:
                    try: send(str(message["chat"]["id"]), f"حدث خطأ أثناء تنفيذ الأمر: {str(exc)[:300]}")
                    except Exception: pass
        except Exception:
            time.sleep(5)


def start():
    """Start one daemon polling thread; only when both credentials are configured."""
    global _started, _poll_thread
    with _start_lock:
        token, chat = _credentials()
        if _started or not token or not chat:
            return False
        _started = True
        _poll_thread = threading.Thread(target=_poll, name="telegram-control-bot", daemon=True)
        _poll_thread.start()
        return True
