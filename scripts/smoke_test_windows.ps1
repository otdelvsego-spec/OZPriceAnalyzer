param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath,

    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class SingleInstanceWindowProbe
{
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hWnd);
}
"@

$resolvedExecutable = (Resolve-Path $ExecutablePath).Path
$previousDataRoot = $env:OZON_APP_DATA
$smokeDataRoot = Join-Path ([IO.Path]::GetTempPath()) "OZPriceAnalyzerSmoke-$PID"
$process = $null
$secondProcess = $null

try {
    $env:OZON_APP_DATA = $smokeDataRoot
    $process = Start-Process -FilePath $resolvedExecutable -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $windowTitle = ""

    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) {
            throw "Приложение завершилось при запуске с кодом $($process.ExitCode)."
        }
        $windowTitle = $process.MainWindowTitle
        if ($windowTitle -match "Unhandled exception|Failed to execute script") {
            throw "PyInstaller показал окно ошибки: $windowTitle"
        }
        if ($windowTitle -like "OZ Price Analyzer*") {
            Write-Host "Проверка запуска пройдена: $windowTitle"
            break
        }
    }

    if ($windowTitle -notlike "OZ Price Analyzer*") {
        throw "За $TimeoutSeconds секунд главное окно не появилось. Текущее окно: '$windowTitle'."
    }

    $process.Refresh()
    $firstWindowHandle = $process.MainWindowHandle
    if ($firstWindowHandle -eq [IntPtr]::Zero) {
        throw "Не удалось получить дескриптор первого окна."
    }

    [SingleInstanceWindowProbe]::ShowWindowAsync($firstWindowHandle, 6) | Out-Null
    $minimizeDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while (
        -not [SingleInstanceWindowProbe]::IsIconic($firstWindowHandle) -and
        [DateTime]::UtcNow -lt $minimizeDeadline
    ) {
        Start-Sleep -Milliseconds 100
    }
    if (-not [SingleInstanceWindowProbe]::IsIconic($firstWindowHandle)) {
        throw "Не удалось свернуть первое окно перед проверкой повторного запуска."
    }

    $secondProcess = Start-Process -FilePath $resolvedExecutable -PassThru
    if (-not $secondProcess.WaitForExit(10000)) {
        throw "Второй экземпляр не завершился после активации первого окна."
    }
    if ($secondProcess.ExitCode -ne 0) {
        throw "Второй экземпляр завершился с кодом $($secondProcess.ExitCode)."
    }

    $restoreDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while (
        [SingleInstanceWindowProbe]::IsIconic($firstWindowHandle) -and
        [DateTime]::UtcNow -lt $restoreDeadline
    ) {
        Start-Sleep -Milliseconds 100
    }
    $process.Refresh()
    if ($process.HasExited) {
        throw "Первый экземпляр завершился во время повторного запуска."
    }
    if ([SingleInstanceWindowProbe]::IsIconic($firstWindowHandle)) {
        throw "Повторный запуск не восстановил первое окно."
    }

    Write-Host "Проверка единственного экземпляра пройдена: второе окно не создано, первое восстановлено."
    exit 0
}
finally {
    if ($secondProcess -and -not $secondProcess.HasExited) {
        Stop-Process -Id $secondProcess.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $secondProcess.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
    if ($null -eq $previousDataRoot) {
        Remove-Item Env:OZON_APP_DATA -ErrorAction SilentlyContinue
    }
    else {
        $env:OZON_APP_DATA = $previousDataRoot
    }
    Remove-Item $smokeDataRoot -Recurse -Force -ErrorAction SilentlyContinue
}
