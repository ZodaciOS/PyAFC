@echo off
echo Creating virtual environment in 'venv'...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing required packages...
pip install -r requirements.txt

echo Setup complete. You can now run the application using run.bat
pause
