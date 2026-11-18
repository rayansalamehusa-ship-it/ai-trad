#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d venv ] || { echo "[1/3] إنشاء البيئة الافتراضية..."; python3 -m venv venv || { echo "Python 3.10+ مطلوب"; exit 1; }; }
source venv/bin/activate
echo "[2/3] تثبيت المكتبات..."
pip install -q -r requirements.txt || exit 1
pip install -q -r requirements-window.txt || echo "(تحذير) سيفتح المتصفح بدل نافذة التطبيق"
pip install -q -r requirements-ai.txt || echo "(تحذير) تعذر تثبيت crewai - الوضع المحلي فقط"
[ -f .env ] || cp .env.example .env
echo "[3/3] تشغيل التطبيق..."
python app.py
