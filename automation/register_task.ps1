# Mr.2 Gold 週次バックテストを Windows のタスクスケジューラに登録します（何度実行しても上書き登録）。
# 使い方（リポジトリのフォルダで）:
#   powershell -ExecutionPolicy Bypass -File automation\register_task.ps1
#   powershell -ExecutionPolicy Bypass -File automation\register_task.ps1 -Remove   # 登録を削除
param(
    [string]$TaskName = "Mr2Gold_WeeklyBacktest",
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$Day = "Saturday",
    [string]$At = "09:07",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "タスク「$TaskName」を削除しました。"
    exit 0
}

$repo = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $PSScriptRoot "run_weekly.bat"
if (-not (Test-Path $bat)) { throw "run_weekly.bat が見つかりません: $bat" }
if (-not (Test-Path (Join-Path $PSScriptRoot "config.json"))) {
    Write-Warning "automation\config.json がまだありません。config.example.json をコピーして作成してください（登録は続けます）。"
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
# cmd /c ""パス"" の形にして、スペースや括弧を含むフォルダでも動くようにする
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$bat`"`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
# MT4 は画面のあるアプリなので「ユーザーがログオンしているときのみ実行」（Interactive）
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 12)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description "Mr.2 Gold の週次バックテスト＋ウォークフォワード（結果は Discord に通知）" -Force | Out-Null

Write-Host ""
Write-Host "タスク「$TaskName」を登録しました。"
Write-Host "  実行日時: 毎週 $Day $At（このパソコンの時刻）"
Write-Host "  実行内容: $bat"
Write-Host "  ログ    : $(Join-Path $repo 'reports\last_run.log')"
Write-Host ""
Write-Host "注意:"
Write-Host "  - パソコンの電源を入れ、$user でサインインしたままにしてください（画面ロックは OK、サインアウトは NG）。"
Write-Host "  - その時間にバックテスト用 MT4（C:\MT4_Backtest など）を開いたままにしないでください。"
Write-Host "  - 予定時刻に電源が切れていた場合は、次に起動したときに実行されます。"
Write-Host ""
Write-Host "今すぐ試すには:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "削除するには:    powershell -ExecutionPolicy Bypass -File automation\register_task.ps1 -Remove"
