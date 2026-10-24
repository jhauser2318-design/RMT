@echo off
REM ------------------------------------------------------------------
REM  RMT (Risky Money Time) - one-time setup. Double-click this file.
REM  It installs everything and puts an RMT icon on your Desktop.
REM ------------------------------------------------------------------
title RMT - setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
if errorlevel 1 pause
