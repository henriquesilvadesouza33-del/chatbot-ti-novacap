@echo off
title Servidor e Chat - TI NOVACAP
cd /d "%~dp0"
set "URL=http://localhost:5000"

echo Verificando porta 5000...
netstat -ano | findstr /C:":5000" | findstr /C:"LISTENING" >nul
if not errorlevel 1 goto abrir_chat

echo Iniciando o Servidor de IA da Novacap...
start "Servidor TI Novacap" /min python server.py
echo Aguardando a inicializacao do sistema...
timeout /t 4 /nobreak >nul

:abrir_chat
echo Abrindo o Chatbot no seu navegador padrao...
start "" "%URL%"
exit
