@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv (
  echo [1/3] انشاء البيئة الافتراضية...
  python -m venv venv || (echo Python غير مثبت! ثبته من python.org & pause & exit /b 1)
)
call venv\Scripts\activate
echo [2/3] تثبيت المكتبات الاساسية...
python -m pip install -q -r requirements.txt || (echo فشل التثبيت & pause & exit /b 1)
python -m pip install -q -r requirements-window.txt || echo (تحذير) تعذر تثبيت نافذة التطبيق - سيفتح المتصفح بدلا منها
python -m pip install -q -r requirements-ai.txt || echo (تحذير) تعذر تثبيت crewai - سيعمل الوضع المحلي فقط
if not exist .env copy .env.example .env >nul
echo [3/3] تشغيل التطبيق...
python app.py
pause
