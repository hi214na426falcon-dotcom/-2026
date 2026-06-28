@echo off
chcp 65001 >nul
echo note投稿用のChromeを起動します...

set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME%" (
  echo.
  echo Chromeが見つかりませんでした。
  echo Chromeをインストールしてから、もう一度このファイルを実行してください。
  echo.
  pause
  exit /b 1
)

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\note-chrome-profile" "https://note.com/login"

echo.
echo Chromeを起動しました。
echo この画面のChromeで note.com にログインしてください（初回だけ）。
echo ログインが終わったら、PowerShellで次を実行:
echo     python publish_note.py drafts/01_原体験.md
echo.
echo （このウィンドウは閉じてOKです）
echo.
pause
