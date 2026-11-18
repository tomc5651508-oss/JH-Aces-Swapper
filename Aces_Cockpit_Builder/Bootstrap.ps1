param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$root = $PSScriptRoot
$cache = Join-Path $root '.tools'
$downloads = Join-Path $cache 'downloads'
$runtime = Join-Path $cache 'python'
New-Item -ItemType Directory -Force -Path $downloads | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Fetch([string]$Url,[string]$Name,[string]$Sha) {
    $p = Join-Path $downloads $Name
    if (!(Test-Path -LiteralPath $p) -or (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash -ne $Sha) {
        Write-Host "Downloading $Name ..."
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile "$p.download"
        if ((Get-FileHash -LiteralPath "$p.download" -Algorithm SHA256).Hash -ne $Sha) { throw "Checksum mismatch for $Name" }
        Move-Item -LiteralPath "$p.download" -Destination $p -Force
    }
    return $p
}
function Run-Python([string[]]$Arguments) {
    $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $script:python @Arguments
    $code = $LASTEXITCODE; $ErrorActionPreference = $saved
    if ($code -ne 0) { throw "Python step failed (exit $code). See the build log above." }
}
try {
    $python = Join-Path $runtime 'python.exe'
    if (!(Test-Path -LiteralPath $python)) {
        Write-Output 'Preparing private Python 3.11.9 runtime (no system installation needed).'
        $zip = Fetch 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' 'python.zip' '009D6BF7E3B2DDCA3D784FA09F90FE54336D5B60F0E0F305C37F400BF83CFD3B'
        Expand-Archive -LiteralPath $zip -DestinationPath $runtime -Force
    }
    @('python311.zip','.','Lib\site-packages','..\..\toolkit','import site') | Set-Content -LiteralPath (Join-Path $runtime 'python311._pth') -Encoding Ascii
    $requirements = Join-Path $root 'toolkit\requirements.txt'
    $reqHash = (Get-FileHash -LiteralPath $requirements).Hash
    $ready = Join-Path $cache 'requirements.ready'
    if (!(Test-Path -LiteralPath $ready) -or (Get-Content -LiteralPath $ready -Raw).Trim() -ne $reqHash) {
        $getpip = Fetch 'https://raw.githubusercontent.com/pypa/get-pip/8c427468071b5d15717839ffd76c53a96df8b703/public/get-pip.py' 'get-pip.py' '356E0D0DE21CDC348C3394084D90939B85E4246C4D14C76AEE6CA4F46646EA98'
        Run-Python @($getpip,'--no-warn-script-location','--disable-pip-version-check')
        Write-Output 'Installing the pinned builder dependencies. First setup may take several minutes.'
        Run-Python @('-m','pip','install','--disable-pip-version-check','--no-warn-script-location','--only-binary=:all:','-r',$requirements)
        Run-Python @((Join-Path $root 'toolkit\dependency_check.py'))
        Set-Content -LiteralPath $ready -Value $reqHash -Encoding Ascii
    }
    $env:PYTHONUNBUFFERED = '1'
    Run-Python @((Join-Path $root 'toolkit\worker.py'),'--config',$ConfigPath)
    exit 0
} catch {
    Write-Output ('BUILD FAILED: ' + $_.Exception.Message)
    exit 1
}
