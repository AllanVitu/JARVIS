@echo off
REM Lanceur JARVIS : utilise le venv du projet, ou que tu sois.
REM   jarvis            -> mode texte
REM   jarvis --voix     -> mode vocal
REM   jarvis "question" -> reponse unique puis sortie
"%~dp0.venv\Scripts\python.exe" "%~dp0jarvis.py" %*
