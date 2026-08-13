param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath,

    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path $ExecutablePath).Path
$previousDataRoot = $env:OZON_APP_DATA
$smokeDataRoot = Join-Path ([IO.Path]::GetTempPath()) "OZPriceAnalyzerSmoke-$PID"
$process = $null

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
            exit 0
        }
    }

    throw "За $TimeoutSeconds секунд главное окно не появилось. Текущее окно: '$windowTitle'."
}
finally {
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
