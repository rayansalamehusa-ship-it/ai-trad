"""تطبيق سطح المكتب المحلي: خادم Flask على 127.0.0.1 + نافذة بتصميم iOS."""
import os, socket, sys, threading, time, uuid, webbrowser
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv, set_key
from flask import Flask, jsonify, request, send_from_directory

import engine, notify, tracker, intelligence, paper_trading, orderflow, telegram_bot, mt5_demo
from tools import assets as A, brain, lab, market_tools

BASE = Path(__file__).resolve().parent
ENV = BASE / ".env"
load_dotenv(ENV)
app = Flask(__name__, static_folder=str(BASE / "static"))
jobs, alerts, last_alert, lock = {}, [], {}, threading.Lock()
DEFAULT_WL = "BTC,ETH,SOL,XAU/USD,EUR/USD,USD/JPY,GBP/USD"


norm = A.normalize


def style_of(v):
    return "scalp" if v == "scalp" else "swing"


def watchlist():
    return [norm(x) for x in (os.getenv("WATCHLIST") or DEFAULT_WL).split(",") if x.strip()]


def num(var, default):
    try:
        return float(os.getenv(var) or default)
    except ValueError:
        return default


@app.before_request
def guard():  # يمنع المواقع الأخرى من إرسال طلبات POST للتطبيق المحلي
    if request.method != "GET" and request.headers.get("X-App") != "1":
        return jsonify(error="forbidden"), 403


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
def status():
    try:
        import crewai  # noqa: F401
        ai = True
    except ImportError:
        ai = False
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    return jsonify(ai_installed=ai, key_set=bool(key), xai_set=bool(os.getenv("XAI_API_KEY")), grok_model=os.getenv("GROK_MODEL", "grok-4.7"), grok_review=os.getenv("GROK_REVIEW", "1") != "0", alert_id=len(alerts),
                   worker=os.getenv("WORKER_MODEL", "gemini/gemini-3.5-flash"), ceo=os.getenv("CEO_MODEL", "gemini/gemini-3.5-flash"),
                   tg_set=bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
                   tg_control=bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
                   watchlist=",".join(x.split("/")[0] for x in watchlist()), auto_min=int(num("AUTO_SCAN_MIN", 0)),
                   capital=num("AUTO_CAPITAL", 1000), tg_chat=os.getenv("TELEGRAM_CHAT_ID", ""),
                   auto_mode=os.getenv("AUTO_MODE", "swing"), lab_hours=int(num("LAB_AUTO_HOURS", 0)), lab=lab.summary(), brain=brain.summary(), assets=A.groups(),
                   steps=[{"key": k, "name": n, "en": e} for k, n, e in engine.STEPS])


@app.post("/api/settings")
def settings():
    d = request.get_json(force=True)
    fields = {"key": "GEMINI_API_KEY", "worker": "WORKER_MODEL", "ceo": "CEO_MODEL", "tg_token": "TELEGRAM_BOT_TOKEN",
              "tg_chat": "TELEGRAM_CHAT_ID", "watchlist": "WATCHLIST", "auto_min": "AUTO_SCAN_MIN", "capital": "AUTO_CAPITAL",
              "auto_mode": "AUTO_MODE", "lab_hours": "LAB_AUTO_HOURS",
              "xai_key": "XAI_API_KEY", "grok_model": "GROK_MODEL", "grok_review": "GROK_REVIEW"}
    vals = {var: str(d.get(f, "")).strip() for f, var in fields.items()}
    try:
        if vals["AUTO_SCAN_MIN"] and int(vals["AUTO_SCAN_MIN"]) not in range(0, 1441):
            raise ValueError
        if vals["AUTO_SCAN_MIN"] and 0 < int(vals["AUTO_SCAN_MIN"]) < 5:
            vals["AUTO_SCAN_MIN"] = "5"           # حد أدنى لتفادي حظر المنصات
        if vals["LAB_AUTO_HOURS"] and int(vals["LAB_AUTO_HOURS"]) not in range(0, 169):
            raise ValueError
        if vals["AUTO_MODE"] and vals["AUTO_MODE"] not in ("swing", "scalp", "both"):
            raise ValueError
        if vals["GROK_REVIEW"] and vals["GROK_REVIEW"] not in ("0", "1"):
            raise ValueError
        if vals["AUTO_CAPITAL"] and float(vals["AUTO_CAPITAL"]) <= 0:
            raise ValueError
    except ValueError:
        return jsonify(error="قيمة غير صالحة في المسح التلقائي أو رأس المال"), 400
    ENV.touch(exist_ok=True)
    for var, v in vals.items():
        if v:
            set_key(str(ENV), var, v)
            os.environ[var] = v
    # If Telegram credentials were added from the settings screen, start polling now.
    telegram_bot.start()
    return jsonify(ok=True)


@app.post("/api/notify/test")
def notify_test():
    ok, err = notify.send("✅ تنبيه تجريبي من شركة التداول الذكية — Telegram يعمل.")
    return jsonify(ok=ok, error=err)


@app.post("/api/run")
def run():
    d = request.get_json(force=True)
    symbol = norm(d.get("symbol") or "BTC/USDT")
    try:
        capital = float(d.get("capital") or 1000)
        assert capital > 0
    except Exception:  # noqa: BLE001
        return jsonify(error="رأس المال غير صالح"), 400
    mode = "ai" if d.get("mode") == "ai" else "local"
    style = style_of(d.get("style"))
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "type": "run", "status": "running", "symbol": symbol, "capital": capital, "mode": mode, "style": style,
           "steps": {k: {"state": "wait", "text": ""} for k in engine.KEYS}, "result": None, "error": None}
    jobs[jid] = job

    def on_step(key, state, text):
        with lock:
            job["steps"][key] = {"state": state, "text": text}

    def work():
        try:
            job["result"] = engine.run_analysis(symbol, capital, mode, style, on_step)
            job["result"]["mt5_execution"] = mt5_demo.maybe_execute(job["result"])
            job["status"] = "done"
            tracker.add(tracker.make_entry(symbol, capital, mode, job["result"]))
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "error", str(e)

    threading.Thread(target=work, daemon=True).start()
    return jsonify(id=jid)


@app.post("/api/scan")
def scan():
    d = request.get_json(force=True)
    coins = [norm(x) for x in d.get("coins", [])] or watchlist()
    capital = float(d.get("capital") or 1000)
    style = style_of(d.get("style"))
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "type": "scan", "status": "running", "total": len(coins), "done": 0, "results": [], "error": None}
    jobs[jid] = job

    def on_row(row):
        with lock:
            job["results"].append(row)
            job["done"] += 1

    def work():
        engine.scan(coins, capital, style, on_row)
        job["status"] = "done"

    threading.Thread(target=work, daemon=True).start()
    return jsonify(id=jid)


@app.get("/api/job/<jid>")
def job(jid):
    j = jobs.get(jid)
    return (jsonify(j), 200) if j else (jsonify(error="not found"), 404)


@app.post("/api/intelligence")
def market_intelligence():
    """تحليل سياق السوق من شموع مغلقة متعددة الأطر؛ لا يصدر أمراً تداولياً."""
    d = request.get_json(force=True)
    symbol = norm(d.get("symbol") or "BTC/USDT")
    frames, errors, sources = {}, {}, {}
    for tf in ("1h", "15m", "5m"):
        try:
            source, df = market_tools.candles(symbol, tf, limit=500)
            frames[tf] = intelligence.analyze_frame(df, tf)
            sources[tf] = source
        except Exception as e:  # noqa: BLE001
            errors[tf] = str(e)[:240]
    if not frames:
        return jsonify(error="تعذر تحليل الأصل من مصادر البيانات المتاحة", details=errors), 502
    return jsonify(symbol=symbol, frames=frames, synthesis=intelligence.combine(frames), sources=sources,
                   missing_frames=errors, disclaimer="تحليل احتمالي من OHLCV؛ ليس تنبؤاً مؤكداً. الحجم تقديري وليس Order Flow حقيقياً.")


@app.post("/api/orderflow")
def orderflow_api():
    """تدفق أوامر مباشر من منصة كريبتو؛ مستقل عن تحليل OHLCV."""
    d = request.get_json(force=True)
    symbol = norm(d.get("symbol") or "BTC/USDT")
    try:
        return jsonify(orderflow.analyze(symbol))
    except Exception as e:  # noqa: BLE001
        return jsonify(available=False, error=str(e)[:300]), 502


@app.get("/api/mt5/status")
def mt5_status():
    return jsonify(mt5_demo.status())


@app.post("/api/mt5/connect")
def mt5_connect():
    return jsonify(mt5_demo.connect())


@app.get("/api/mt5/performance")
def mt5_performance():
    return jsonify(mt5_demo.performance())


@app.post("/api/mt5/auto")
def mt5_auto():
    d = request.get_json(force=True)
    enabled = bool(d.get("enabled"))
    if enabled:
        state = mt5_demo.status()
        if not state.get("connected") or not state.get("demo"):
            return jsonify(ok=False, error=state.get("error") or "اتصل بحساب Demo أولاً"), 400
    try:
        settings = mt5_demo.set_auto(enabled, d.get("risk_pct", 0.5))
        return jsonify(ok=True, settings=settings)
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/api/mt5/execute")
def mt5_execute():
    d = request.get_json(force=True)
    result = d.get("result") or {}
    if result.get("decision") != "APPROVED" or not result.get("plan"):
        return jsonify(ok=False, error="لا يمكن تنفيذ إشارة لم تجتز الاعتماد الصارم"), 400
    cfg = mt5_demo._settings()
    return jsonify(mt5_demo.execute_signal(result["plan"], cfg["risk_pct"]))


@app.get("/api/paper")
def paper_status():
    return jsonify(paper_trading.snapshot(refresh=request.args.get("refresh") == "1"))


@app.post("/api/paper/open")
def paper_open():
    d = request.get_json(force=True)
    try:
        symbol = norm(d.get("symbol") or "BTC/USDT")
        p = paper_trading.open_position(symbol, d.get("side"), d.get("entry"), d.get("stop"), d.get("target"), d.get("risk_pct", 0.5))
        return jsonify(ok=True, position=p, account=paper_trading.snapshot())
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400


@app.post("/api/paper/close")
def paper_close():
    d = request.get_json(force=True)
    try:
        p = paper_trading.close_position(str(d.get("id") or ""), d.get("exit_price"), d.get("reason", "MANUAL"))
        return jsonify(ok=True, trade=p, account=paper_trading.snapshot())
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400


@app.post("/api/paper/reset")
def paper_reset():
    d = paper_trading.load()
    if d.get("positions"):
        return jsonify(error="أغلق المراكز الورقية المفتوحة قبل إعادة ضبط المحفظة"), 409
    return jsonify(ok=True, account=paper_trading.reset())


@app.get("/api/history")
def history():
    h = tracker.load()
    return jsonify(items=h, stats=tracker.stats(h))


@app.post("/api/tracker/refresh")
def refresh():
    tracker.refresh()
    return jsonify(ok=True)


@app.post("/api/history/clear")
def clear():
    tracker.save([])
    return jsonify(ok=True)


@app.get("/api/alerts")
def get_alerts():
    after = int(request.args.get("after", 0))
    return jsonify([a for a in alerts if a["id"] > after])


@app.post("/api/telegram/send")
def telegram_send():
    """يرسل خطة صفقة تحليل منتهٍ إلى Telegram (بطلب المستخدم)."""
    j = jobs.get(request.get_json(force=True).get("job"))
    r = j and j.get("result")
    if not r or not r.get("plan"):
        return jsonify(ok=False, error="لا توجد خطة صفقة لإرسالها (الحالة: انتظار)"), 400
    ok, err = notify.send(notify.format_signal(r))
    return jsonify(ok=ok, error=err)


# ---------------------------------------------------------------- مختبر الاستراتيجيات
@app.get("/api/lab")
def lab_list():
    lib = lab.load()
    return jsonify(items=lib["items"], meta=lib["meta"], summary=lab.summary())


@app.post("/api/lab/discover")
def lab_discover():
    d = request.get_json(force=True)
    use_llm = bool(d.get("llm"))
    if use_llm and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return jsonify(error="أضف مفتاح Gemini من الإعدادات أولاً"), 400
    if lab.summary()["running"]:
        return jsonify(error="دورة بحث أخرى تعمل الآن"), 409
    n = max(10, min(int(d.get("n") or 60), 200))
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "type": "lab", "status": "running", "msg": "بدء البحث…", "pct": 0, "result": None, "error": None}
    jobs[jid] = job

    def prog(msg, pct):
        job["msg"], job["pct"] = msg, round(pct)

    def work():
        try:
            job["result"] = lab.discover(n, use_llm, prog)
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "error", str(e)

    threading.Thread(target=work, daemon=True).start()
    return jsonify(id=jid)


@app.get("/api/brain")
def brain_get():
    kn = brain.load()
    return jsonify(summary=brain.summary(), relations=[{**r, "text": brain.relation_text(r)} for r in kn["relations"]], log=kn["log"])


@app.post("/api/brain/cycle")
def brain_cycle():
    d = request.get_json(force=True)
    use_llm = bool(d.get("llm"))
    if use_llm and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return jsonify(error="أضف مفتاح Gemini من الإعدادات أولاً"), 400
    if brain.running():
        return jsonify(error="دورة تعلم أو بحث تعمل الآن"), 409
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "type": "brain", "status": "running", "msg": "بدء دورة التعلم…", "pct": 0, "result": None, "error": None}
    jobs[jid] = job

    def prog(msg, pct):
        job["msg"], job["pct"] = msg, round(pct)

    def work():
        try:
            job["result"] = brain.cycle(prog, use_llm)
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "error", str(e)

    threading.Thread(target=work, daemon=True).start()
    return jsonify(id=jid)


@app.post("/api/lab/toggle")
def lab_toggle():
    d = request.get_json(force=True)
    cur = next((i for i in lab.load()["items"] if i["id"] == d.get("id")), None)
    if not cur:
        return jsonify(error="not found"), 404
    lab.set_status(cur["id"], "retired" if cur["status"] == "active" else "active")
    return jsonify(ok=True)


@app.post("/api/lab/delete")
def lab_delete():
    return jsonify(ok=lab.delete(request.get_json(force=True).get("id", "")))


def _alert(sym, r, tag=""):
    txt = notify.format_signal(r)
    with lock:
        alerts.append({"id": len(alerts) + 1, "time": datetime.now().strftime("%H:%M"), "symbol": sym, "text": txt, "tag": tag})
    notify.send(txt)


def autoscan():
    """مسح تلقائي دوري لقائمة المتابعة (صفقات و/أو سكالبينج)؛ ينبّه فقط عند إشارة جديدة موافق عليها،
    مع فترة تبريد لكل (أصل، وضع، اتجاه): 12 ساعة للصفقات و60 دقيقة للسكالبينج."""
    last = 0.0
    while True:
        time.sleep(20)
        mins = int(num("AUTO_SCAN_MIN", 0))
        if mins <= 0 or time.time() - last < mins * 60:
            continue
        last, cap = time.time(), num("AUTO_CAPITAL", 1000)
        am = os.getenv("AUTO_MODE", "swing")
        for style in (["swing", "scalp"] if am == "both" else [style_of(am)]):
            cool = 12 * 3600 if style == "swing" else 3600
            for sym in watchlist():
                try:
                    r = engine.analyze(sym, cap, style, light=True)
                    hot = lambda x: x["plan"] and x["decision"] == "APPROVED"  # noqa: E731
                    if not hot(r):
                        continue
                    key = (sym, style, r["action"])
                    if time.time() - last_alert.get(key, 0) < cool:
                        continue
                    r = engine.analyze(sym, cap, style)        # تأكيد كامل قبل التنبيه
                    if not hot(r):
                        continue
                except Exception:  # noqa: BLE001
                    continue
                last_alert[key] = time.time()
                mt5_demo.maybe_execute(r)
                tracker.add(tracker.make_entry(sym, cap, "auto", r))
                _alert(sym, r)


def lab_loop():
    """التعلم المستمر: كل N ساعة (من الإعدادات) تعمل دورة تعلم كاملة (علاقات + استراتيجيات + تعلم من الصفقات الحية) ويصلك تقرير Telegram."""
    while True:
        time.sleep(60)
        hrs = int(num("LAB_AUTO_HOURS", 0))
        if hrs <= 0 or brain.running():
            continue
        last = brain.load().get("last_cycle")
        if last and (datetime.now() - datetime.fromisoformat(last)).total_seconds() < hrs * 3600:
            continue
        try:
            e = brain.cycle(use_llm=bool(os.getenv("GEMINI_API_KEY")) and os.getenv("LAB_USE_LLM", "0") == "1")
            if e["strategies_added"] or e["relations_added"] or e["strategies_retired"] or e["live_retired"]:
                notify.send(brain.report_text(e))
        except Exception:  # noqa: BLE001
            pass


def free_port(pref=5057):
    with socket.socket() as s:
        return pref if s.connect_ex(("127.0.0.1", pref)) != 0 else 0


if __name__ == "__main__":
    headless = "--headless" in sys.argv          # بلا نافذة: للتشغيل المستمر على خادم/جهاز دائم لإرسال تنبيهات Telegram
    port = free_port() or 5057 + int(time.time()) % 500
    url = f"http://127.0.0.1:{port}"
    telegram_bot.start()
    threading.Thread(target=autoscan, daemon=True).start()
    threading.Thread(target=lab_loop, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, threaded=True), daemon=True).start()
    time.sleep(1)
    if headless:
        print(f"وضع بلا نافذة يعمل — الواجهة على {url} — المسح التلقائي وتنبيهات Telegram نشطة حسب الإعدادات (Ctrl+C للإيقاف)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sys.exit(0)
    try:
        import webview
        webview.create_window("AI Trading Firm", url, width=440, height=900, min_size=(380, 640))
        webview.start()
    except Exception:  # noqa: BLE001
        print(f"\nافتح التطبيق في المتصفح:  {url}\n(للإغلاق اضغط Ctrl+C)")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sys.exit(0)
