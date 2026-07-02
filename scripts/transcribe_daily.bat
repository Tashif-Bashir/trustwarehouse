@echo off
rem Daily Ascend call transcription on the PC GPU (RTX 2060, large-v3-turbo).
rem Scheduled via Task Scheduler: weekdays 09:30. Audio is streamed to %TEMP%
rem and deleted immediately after transcription - nothing is stored on this PC.
cd /d C:\Users\bashi\trustwarehouse
set ASCEND_WHISPER_DEVICE=cuda
set ASCEND_WHISPER_MODEL=large-v3-turbo
set ASCEND_TRANSCRIBE_LOOKBACK_DAYS=4
set ASCEND_TRANSCRIBE_MAX_PER_RUN=500
C:\Python313\python.exe -m ingestion.ascend.transcribe >> "%TEMP%\ascend_transcribe.log" 2>&1
