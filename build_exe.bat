@echo off
rem Локальная сборка ACC-Marshal.exe (нужен Python с tkinter)
pip install pyinstaller paramiko
pyinstaller --noconfirm --onefile --windowed --name ACC-Marshal --hidden-import paramiko run.py
echo.
echo Готово: dist\ACC-Marshal.exe
pause
