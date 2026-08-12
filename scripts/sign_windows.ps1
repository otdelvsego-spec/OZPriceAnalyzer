param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:WINDOWS_CERTIFICATE_BASE64)) {
    Write-Host "Сертификат не настроен: сборка останется без цифровой подписи."
    exit 0
}
if ([string]::IsNullOrWhiteSpace($env:WINDOWS_CERTIFICATE_PASSWORD)) {
    throw "Задан WINDOWS_CERTIFICATE_BASE64, но отсутствует WINDOWS_CERTIFICATE_PASSWORD."
}

$signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $signTool) {
    throw "SignTool не найден в Windows SDK."
}

$temporaryRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$certificatePath = Join-Path $temporaryRoot "ozpriceanalyzer-signing.pfx"
try {
    [IO.File]::WriteAllBytes(
        $certificatePath,
        [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_BASE64)
    )
    & $signTool.FullName sign `
        /fd SHA256 `
        /tr "http://timestamp.digicert.com" `
        /td SHA256 `
        /f $certificatePath `
        /p $env:WINDOWS_CERTIFICATE_PASSWORD `
        $ExecutablePath
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool завершился с кодом $LASTEXITCODE."
    }
    & $signTool.FullName verify /pa /v $ExecutablePath
    if ($LASTEXITCODE -ne 0) {
        throw "Проверка цифровой подписи завершилась с кодом $LASTEXITCODE."
    }
}
finally {
    Remove-Item $certificatePath -Force -ErrorAction SilentlyContinue
}
