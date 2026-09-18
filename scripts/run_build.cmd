@echo off
rem Weekly pipeline run (called by Task Scheduler). Logs to data\build.log.
cd /d "%~dp0.."
if not exist data mkdir data
echo ==== %DATE% %TIME% ==== >> data\build.log
".venv\Scripts\python.exe" -m pipeline.build >> data\build.log 2>&1
