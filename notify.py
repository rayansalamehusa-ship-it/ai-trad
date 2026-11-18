"""تنبيهات Telegram: الصفقة كاملة (شراء/بيع عند سعر + هدف الربح + وقف الخسارة)."""
import os
import requests


def send(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False, "لم يتم ضبط Telegram"
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text}, timeout=10)
        return r.ok, "" if r.ok else r.text[:200]
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def format_signal(r):
    """رسالة الصفقة من نتيجة engine.analyze (يجب أن تحتوي r['plan'])."""
    p = r["plan"]
    buy = p["action"] == "BUY"
    sym = p["symbol"]
    lines = [f"{'🟢 شراء BUY' if buy else '🔴 بيع SELL'} — {sym}",
             f"⏱ {r['mode_label']} · فريم {p['entry_tf']} · درجة {p['grade']} ({p['score']}/100)",
             f"💰 السعر (الدخول): {p['entry']}" + (f"\n   الأفضل الدخول عند: {p['entry_limit']}" if p.get("entry_limit") else ""),
             f"🎯 الربح Take Profit 1: {p['take_profit']}",
             f"🎯 الربح Take Profit 2: {p['take_profit2']}",
             f"🛑 وقف الخسارة Stop Loss: {p['stop_loss']}",
             f"⚖️ نسبة العائد للمخاطرة 1:{p['rr']}",
             f"📊 قوة الاتجاه: شراء {r['buy_pct']}% / بيع {r['sell_pct']}%"]
    if p.get("win_rate_est") is not None:
        lines.append(f"📈 نجاح تاريخي مقدّر: {p['win_rate_est']}% (من {p['win_n']} صفقة)")
    g = (r.get("grok") or {}).get("pulse")
    if g and "sentiment" in g:
        lines.append("🐦 مزاج X (Grok): " + {-2: "سلبي جداً", -1: "سلبي", 0: "محايد", 1: "إيجابي", 2: "إيجابي جداً"}[g["sentiment"]])
    lines.append(f"💼 الحجم: ${p['size_usd']} (خسارة قصوى ${p['risk_usd']})" + (f" — رافعة ≈ {p['leverage']}×" if p.get("leverage", 0) > 1 else ""))
    if p.get("strategy"):
        lines.append("🧠 الاستراتيجية: " + "، ".join(p["strategy"][:2]))
    lines.append("⚠️ تحليل ومحاكاة وليس نصيحة مالية — لا تنفيذ تلقائي.")
    return "\n".join(lines)
