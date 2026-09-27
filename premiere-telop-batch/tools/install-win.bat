@echo off
chcp 65001 > nul
rem テロップ一括調整 — Windows 用インストーラ（ダブルクリックで実行できます）
set "SRC=%~dp0.."
set "DEST=%APPDATA%\Adobe\CEP\extensions\com.yasu29fr.telopbatch"

rem 署名なし拡張機能を読み込めるようにする（CEP 9〜13）
for %%v in (9 10 11 12 13) do (
  reg add "HKCU\Software\Adobe\CSXS.%%v" /v PlayerDebugMode /t REG_SZ /d 1 /f > nul
)

if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
xcopy "%SRC%\CSXS" "%DEST%\CSXS\" /e /i /y > nul
xcopy "%SRC%\css"  "%DEST%\css\"  /e /i /y > nul
xcopy "%SRC%\js"   "%DEST%\js\"   /e /i /y > nul
xcopy "%SRC%\jsx"  "%DEST%\jsx\"  /e /i /y > nul
copy "%SRC%\index.html" "%DEST%\" > nul
copy "%SRC%\.debug" "%DEST%\" > nul

echo インストールしました: %DEST%
echo Premiere Pro を再起動し、[ウィンドウ] ^> [エクステンション] ^> [テロップ一括調整] を開いてください。
pause
