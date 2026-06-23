@echo off
echo ==============================================
echo Installing Dependencies from requirements.txt...
echo ==============================================
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo Error installing dependencies.
    pause
    exit /b %ERRORLEVEL%
)

echo ==============================================
echo Installing Playwright Browsers...
echo ==============================================
playwright install chromium
if %ERRORLEVEL% neq 0 (
    echo Error installing Playwright browsers.
    pause
    exit /b %ERRORLEVEL%
)

echo ==============================================
echo Starting Streamlit Web App...
echo ==============================================
streamlit run app.py
