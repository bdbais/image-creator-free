@echo off
rem Avvia Image Creator Free.
rem
rem La finestra gira con il Python dell'ambiente di calcolo, non dentro
rem l'eseguibile: cosi' il processo che carica il modello e' un normale
rem processo Python e parte senza sorprese. L'eseguibile serve solo a
rem preparare l'ambiente la prima volta (o quando manca qualcosa).

setlocal
chcp 65001 >nul
set "BASE=%~dp0"
if defined ICF_DATA_DIR (set "DATA=%ICF_DATA_DIR%") else set "DATA=%LOCALAPPDATA%\ImageCreatorFree"

call :trova
if not defined PYW (
    "%BASE%ImageCreatorFree.exe" --prepara
    call :trova
)
if not defined PYW exit /b 1

set "PYTHONPATH=%BASE%app\src"
set "PYTHONUTF8=1"
start "" "%PYW%" "%BASE%app\ImageCreatorFree.pyw" %*
exit /b 0

rem Cerca l'ambiente: la cartella scritta dall'app in runtime.txt, altrimenti
rem quella predefinita. Serve anche PySide6, perche' la finestra gira li'.
:trova
set "PYW="
set "RT=%DATA%\runtime"
if exist "%DATA%\runtime.txt" set /p RT=<"%DATA%\runtime.txt"
if not exist "%RT%\runtime.json" exit /b 0
if not exist "%RT%\Lib\site-packages\PySide6\__init__.py" exit /b 0
if exist "%RT%\Scripts\pythonw.exe" (
    set "PYW=%RT%\Scripts\pythonw.exe"
) else if exist "%RT%\pythonw.exe" (
    set "PYW=%RT%\pythonw.exe"
)
exit /b 0
