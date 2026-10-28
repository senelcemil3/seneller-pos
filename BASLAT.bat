@echo off
chcp 65001 >nul
title SENELLER POS - Satis, Stok ve Montaj Sistemi
cd /d "%~dp0"
echo Eski acik kalan sunucu islemleri temizleniyor...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000"') do taskkill /F /PID %%a >nul 2>&1
taskkill /F /IM cloudflared.exe >nul 2>&1
start "" "http://127.0.0.1:5000/oto-giris?hesap=admin&k=snl2026pos"
py -u run.py
pause
