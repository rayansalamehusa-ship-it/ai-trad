"""Grok (xAI): نبض منصة X للأصل + رأي ثانٍ مستقل على الخطة. استشاري فقط: لا يغيّر الأرقام ولا مستويات الصفقة.
يستعمل Responses API مع أداة x_search من xAI. مخرجات Grok تُعامل كبيانات غير موثوقة (تُقصّ وتُحدّ قبل استعمالها)."""
import json, os, re, time
from datetime import datetime, timedelta, timezone
import requests

URL = "https://api.x.ai/v1/responses"
_cache = {}
ASSET_HINT = {"crypto": "عملة {c} الرقمية (سعرها، أخبارها، المحللون، الحيتان، التنظيمات)",
              "metal": "الذهب/الفضة {s} (الفيدرالي، التضخم، الدولار، التوترات الجيوسياسية، البنوك المركزية)",
              "forex": "زوج العملات {s} (قرارات البنوك المركزية، بيانات التضخم والوظائف، تصريحات المسؤولين)",
              "stock": "سهم {s} (الأرباح، توجيهات الشركة، تصنيفات المحللين، القطاع، الأخبار العاجلة)",
              "index": "مؤشر الدولار DXY (الفيدرالي، العوائد، بيانات أمريكا)"}


def available():
    return bool(os.getenv("XAI_API_KEY"))


def model():
    return os.getenv("GROK_MODEL", "").strip() or "grok-4.7"


def _ask(prompt, tools=None, max_turns=2, timeout=100):
    body = {"model": model(), "input": prompt}
    if tools:
        body.update(tools=tools, max_turns=max_turns)
    r = requests.post(URL, headers={"Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"}, json=body, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"xAI {r.status_code}: {r.text[:180]}")
    d = r.json()
    txt = d.get("output_text") or "".join(p.get("text", "") for o in d.get("output", []) if o.get("type") == "message"
                                          for p in o.get("content", []) if isinstance(p, dict))
    return txt


def _json(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("رد Grok بلا JSON")
    return json.loads(m.group(0))


def _s(v, n):
    return str(v or "")[:n]


def x_pulse(symbol, kind, hours=48):
    """مزاج X لآخر 48 ساعة: {sentiment -2..2, summary, posts[], risks[], confidence}. مخزّن 20 دقيقة لتوفير التكلفة."""
    hit = _cache.get(("p", symbol))
    if hit and time.time() - hit[0] < 1200:
        return hit[1]
    base = symbol.split("/")[0]
    topic = ASSET_HINT[kind].format(c=base, s=symbol)
    frm = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")
    prompt = (f"ابحث في منصة X عما يُنشر خلال آخر {hours} ساعة عن: {topic}. اعتمد على حسابات موثوقة (محللون معروفون، مؤسسات، وكالات أخبار) "
              "وتجاهل الإعلانات والبوتات وإشارات التوصيات المدفوعة والترويج. لا تخترع منشورات. "
              'أعد JSON فقط بلا شرح: {"sentiment": رقم صحيح من -2 (سلبي جداً) إلى 2 (إيجابي جداً), "summary": "ملخص بالعربية في جملتين", '
              '"posts": [{"handle":"@..","gist":"الفكرة بالعربية"}] (حتى 4), "risks": ["مخاطر/أحداث قادمة"] (حتى 3), "confidence": "low|medium|high"}')
    d = _json(_ask(prompt, [{"type": "x_search", "from_date": frm}]))
    out = {"sentiment": max(-2, min(2, int(round(float(d.get("sentiment", 0)))))), "summary": _s(d.get("summary"), 400),
           "posts": [{"handle": _s(p.get("handle"), 30), "gist": _s(p.get("gist"), 160)} for p in (d.get("posts") or [])[:4] if isinstance(p, dict)],
           "risks": [_s(x, 140) for x in (d.get("risks") or [])[:3]],
           "confidence": d.get("confidence") if d.get("confidence") in ("low", "medium", "high") else "low"}
    _cache[("p", symbol)] = (time.time(), out)
    return out


def second_opinion(symbol, analysis_text):
    """مراجعة مستقلة لخطة المحرك: agree / caution / disagree مع نقاط موجزة. استشاري فقط."""
    prompt = (f"أنت مراجع مخاطر مستقل لمتداول. هذا تحليل آلي لـ{symbol}:\n---\n{analysis_text[:3500]}\n---\n"
              "راجعه بنقد صادق: هل المنطق متماسك؟ ما أكبر ثغرة أو خطر؟ لا تُعد حساب الأرقام ولا تخترع بيانات. "
              'أعد JSON فقط: {"verdict":"agree|caution|disagree","points":["حتى 3 نقاط موجزة بالعربية"]}')
    d = _json(_ask(prompt))
    return {"verdict": d.get("verdict") if d.get("verdict") in ("agree", "caution", "disagree") else "caution",
            "points": [_s(x, 220) for x in (d.get("points") or [])[:3]]}


def pulse_text(p):
    mood = {-2: "سلبي جداً", -1: "سلبي", 0: "محايد", 1: "إيجابي", 2: "إيجابي جداً"}[p["sentiment"]]
    lines = [f"🐦 نبض X (Grok): {mood} — ثقة {p['confidence']}", p["summary"]]
    lines += [f"• {x['handle']}: {x['gist']}" for x in p["posts"]]
    lines += [f"⚠️ {x}" for x in p["risks"]]
    return "\n".join(lines)
