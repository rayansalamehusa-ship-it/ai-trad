"""فحص المكتبات وتثبيت الناقص تلقائياً — يحل خطأ: No module named 'yfinance'.

يستعمل نفس مفسّر بايثون الذي يشغّل التطبيق (sys.executable) كي لا تُثبَّت المكتبة في بيئة وتُشغَّل من أخرى،
وهذا هو السبب الأشهر للخطأ (التثبيت في venv والتشغيل من VS Code بمفسّر آخر).
لا يستورد سوى المكتبة القياسية حتى يعمل قبل أي استيراد آخر.
"""
import importlib, importlib.util, subprocess, sys

# اسم الاستيراد -> مواصفة pip
REQUIRED = {
    "flask": "flask>=3.0.0",
    "ccxt": "ccxt>=4.4.0",
    "yfinance": "yfinance>=0.2.50",
    "pandas": "pandas>=2.2.0",
    "numpy": "numpy>=1.26.0",
    "requests": "requests>=2.32.0",
    "dotenv": "python-dotenv>=1.0.1",
}
_tried = set()


def have(mod):
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def missing():
    return [m for m in REQUIRED if not have(m)]


def install(mods, quiet=True):
    """يثبّت المكتبات (أسماء استيراد) بمفسّر بايثون الحالي. يعيد (نجح؟، رسالة)."""
    specs = [REQUIRED.get(m, m) for m in mods]
    if not specs:
        return True, ""
    cmd = [sys.executable, "-m", "pip", "install", "--retries", "1", "--timeout", "20", *(["-q"] if quiet else []), *specs]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        return False, f"تعذر تشغيل pip: {e}"
    importlib.invalidate_caches()
    ok = r.returncode == 0 and all(have(m) for m in mods if m in REQUIRED)
    return ok, "" if ok else (r.stderr or r.stdout or "")[-400:]


def ensure(names=None, announce=True):
    """يثبّت ما ينقص. يعيد قائمة ما بقي ناقصاً بعد المحاولة."""
    todo = [m for m in (names or REQUIRED) if not have(m) and m not in _tried]
    if not todo:
        return [m for m in (names or REQUIRED) if not have(m)]
    if announce:
        print(f"[فحص] مفسّر بايثون: {sys.executable}")
        print(f"[فحص] مكتبات ناقصة: {', '.join(todo)} — جارٍ التثبيت تلقائياً…")
    _tried.update(todo)
    ok, err = install(todo)
    left = [m for m in todo if not have(m)]
    if announce:
        if left:
            print(f"[فحص] تعذر تثبيت: {', '.join(left)}. ثبّتها يدوياً بهذا الأمر:\n       \"{sys.executable}\" -m pip install {' '.join(REQUIRED[m] for m in left)}")
            if err:
                print("       التفاصيل:", err.strip().splitlines()[-1] if err.strip() else "")
        else:
            print("[فحص] تم التثبيت ✓")
    return left


def lazy(mod):
    """استيراد كسول مع تثبيت تلقائي عند الحاجة؛ يعيد الوحدة أو None."""
    if not have(mod):
        if mod in _tried:
            return None
        _tried.add(mod)
        install([mod])
    try:
        return importlib.import_module(mod)
    except ImportError:
        return None


def report():
    return {"python": sys.executable, "missing": missing(),
            "fix": f'"{sys.executable}" -m pip install ' + " ".join(REQUIRED[m] for m in missing()) if missing() else ""}
