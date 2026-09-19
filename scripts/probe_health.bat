@echo off
REM benchmark-health-probe — roda probe diaria e entrega so saida compacta
cd /d "C:\Users\Jason\Desktop\PROJETOS\02 - WORKING\benchmark_geral"
"%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m benchmark_providers.probe_health
