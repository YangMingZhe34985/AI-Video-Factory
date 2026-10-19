param(
    [Parameter(Mandatory=$true)][string]$Backend,
    [Parameter(Mandatory=$true)][string]$Work,
    [string]$Python = 'C:/Users/MingZheYang/anaconda3/envs/video-factory/python.exe',
    [string]$Verifier = (Join-Path $PSScriptRoot 'mysql_verify.py'),
    [int]$Port = 3307
)
$ErrorActionPreference = 'Stop'
if ($Port -eq 3306 -or $Port -lt 1024 -or $Port -gt 65535) { throw 'Only a nondefault high port is allowed' }
$evidenceRoot = [IO.Path]::GetFullPath($Work)
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/')
if (-not $evidenceRoot.StartsWith($tempRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'V10c evidence must be inside TEMP'
}
if (Test-Path -LiteralPath $evidenceRoot) { throw 'Use a fresh evidence folder' }
if (-not (Test-Path -LiteralPath $Verifier -PathType Leaf)) { throw 'Verifier missing' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Conda Python missing' }
if (Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue) { throw 'Requested port is occupied' }
New-Item -ItemType Directory -Path $evidenceRoot | Out-Null
$suffix = (Get-Date -Format 'yyyyMMddHHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$containerName = 'cinecrew-v10c-' + $suffix
$volumeName = 'cinecrew-v10c-' + $suffix + '-data'
$containerOwned = $false
$volumeOwned = $false
$containerRemoved = $false
$volumeRemoved = $false
$verificationExit = $null
$oldPassword = $env:V10C_MYSQL_PASSWORD
$oldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:V10C_MYSQL_PASSWORD = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:PYTHONDONTWRITEBYTECODE = '1'
$record = [ordered]@{ container=$containerName; volume=$volumeName; image='mysql:8.4.4'; port=$Port; started_at=(Get-Date).ToUniversalTime().ToString('o') }
try {
    $imageId = & docker image inspect mysql:8.4.4 --format '{{.Id}}'
    if ($LASTEXITCODE -ne 0) { throw 'Pinned mysql:8.4.4 must be present; no implicit image pull' }
    $record.image_id = $imageId
    $names = & docker container ls -a --format '{{.Names}}'
    if ($LASTEXITCODE -ne 0 -or $names -contains $containerName) { throw 'Container inventory unavailable or name collision' }
    $volumes = & docker volume ls --format '{{.Name}}'
    if ($LASTEXITCODE -ne 0 -or $volumes -contains $volumeName) { throw 'Volume inventory unavailable or name collision' }
    & docker volume create $volumeName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Volume creation failed' }
    $volumeOwned = $true
    & docker run -d --pull=never --name $containerName -p "127.0.0.1:${Port}:3306" `
        --mount "type=volume,src=$volumeName,dst=/var/lib/mysql" `
        -e "MYSQL_ROOT_PASSWORD=$env:V10C_MYSQL_PASSWORD" -e MYSQL_ROOT_HOST=% mysql:8.4.4 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $created = & docker container ls -a --filter "name=^${containerName}$" --format '{{.Names}}'
        $containerOwned = $created -contains $containerName
        throw 'Temporary container start failed'
    }
    $containerOwned = $true
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        & docker exec $containerName mysqladmin ping --host=127.0.0.1 --silent 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Temporary MySQL did not become ready within 120 seconds' }
    & $Python -B $Verifier --backend $Backend --work $evidenceRoot --port $Port
    $verificationExit = $LASTEXITCODE
    $record.verification_exit_code = $verificationExit
    if ($verificationExit -ne 0) { throw 'V10c verification failed; see mysql-evidence.json' }
} catch {
    $record.error = $_.Exception.Message
} finally {
    if ($containerOwned) {
        & docker rm -f $containerName | Out-Null
        $record.container_rm_exit_code = $LASTEXITCODE
        $remaining = & docker container ls -a --filter "name=^${containerName}$" --format '{{.Names}}'
        $containerRemoved = $LASTEXITCODE -eq 0 -and -not ($remaining -contains $containerName)
    }
    if ($volumeOwned) {
        & docker volume rm $volumeName | Out-Null
        $record.volume_rm_exit_code = $LASTEXITCODE
        $remaining = & docker volume ls --filter "name=^${volumeName}$" --format '{{.Name}}'
        $volumeRemoved = $LASTEXITCODE -eq 0 -and -not ($remaining -contains $volumeName)
    }
    $record.container_removed = $containerRemoved
    $record.volume_removed = $volumeRemoved
    $record.finished_at = (Get-Date).ToUniversalTime().ToString('o')
    $record.success = $verificationExit -eq 0 -and $containerRemoved -and $volumeRemoved -and -not $record.Contains('error')
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidenceRoot 'docker-lifecycle.json') -Encoding utf8
    if ($null -eq $oldPassword) { Remove-Item Env:V10C_MYSQL_PASSWORD -ErrorAction SilentlyContinue } else { $env:V10C_MYSQL_PASSWORD=$oldPassword }
    if ($null -eq $oldNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE=$oldNoBytecode }
    $record | ConvertTo-Json -Depth 6
}
if (-not $record.success) { exit 1 }
