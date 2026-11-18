param([switch]$SelfTest,[string]$PreviewPath)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$root = $PSScriptRoot
$slots = Get-Content -LiteralPath (Join-Path $root 'toolkit\slots.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$packName = $slots.pack_name
$planeList = (@($slots.cockpits | ForEach-Object { $_.label }) -join ', ')
$script:process = $null
$script:runOut = ''; $script:runErr = ''
function Steam-Libraries {
    $paths = @()
    try { $steam = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction Stop).SteamPath; $paths += $steam
        $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf) { foreach ($m in [regex]::Matches((Get-Content -LiteralPath $vdf -Raw),'"path"\s+"([^"]+)"')) { $paths += $m.Groups[1].Value.Replace('\\','\') } }
    } catch {}
    return @($paths | Select-Object -Unique)
}
function Find-Game([string]$Name) { foreach ($library in (Steam-Libraries)) { $p = Join-Path $library "steamapps\common\$Name"; if (Test-Path -LiteralPath $p) { return $p } }; return '' }
$form = New-Object Windows.Forms.Form
$form.Text = 'Jungle Hawks - Cockpit Overlay Builder'
$form.ClientSize = New-Object Drawing.Size(970,770)
$form.StartPosition = 'CenterScreen'; $form.MinimumSize = $form.Size
$form.BackColor = [Drawing.Color]::FromArgb(16,28,21); $form.ForeColor = [Drawing.Color]::White
$form.Font = New-Object Drawing.Font('Segoe UI',10)
function Label([string]$Text,[int]$X,[int]$Y,[int]$W,[int]$H) {
    $c = New-Object Windows.Forms.Label; $c.Text = $Text; $c.SetBounds($X,$Y,$W,$H); $form.Controls.Add($c); return $c
}
function Button([string]$Text,[int]$X,[int]$Y,[int]$W,[int]$H) {
    $c = New-Object Windows.Forms.Button; $c.Text = $Text; $c.SetBounds($X,$Y,$W,$H); $c.BackColor = [Drawing.Color]::FromArgb(40,88,49); $c.ForeColor = [Drawing.Color]::White; $c.FlatStyle = 'Flat'; $form.Controls.Add($c); return $c
}
$title = Label 'Build the cockpit overlay from your own Aces install' 24 20 920 38
$title.Font = New-Object Drawing.Font('Segoe UI',18,[Drawing.FontStyle]::Bold)
$intro = Label ($planeList+': sights, gauges, normals and animation bindings. Free, personal use only; see NOTICE.txt.') 24 68 920 30
$boxes = @{}
$script:folderButtons = @()
function Folder-Row([string]$Key,[string]$Title,[int]$Y,[string]$Help) {
    $null = Label $Title 24 $Y 900 25
    $tb = New-Object Windows.Forms.TextBox; $tb.Tag = $Key; $tb.SetBounds(24,($Y+27),800,28); $form.Controls.Add($tb); $script:boxes[$Key] = $tb
    $browse = Button 'Browse...' 836 ($Y+26) 108 31
    $browse.Tag = $tb
    $script:folderButtons += $browse
    $browse.Add_Click({
        $field = $this.Tag; $isOutput = $field.Tag -eq 'output'
        $dialog = New-Object Windows.Forms.FolderBrowserDialog
        $dialog.Description = if ($isOutput) { 'Select the parent folder (for example IL-2 MODS). A new mod folder will be created inside it.' } else { 'Select the installation or base mod folder.' }
        $dialog.ShowNewFolderButton = $true
        if ($field.Text -and (Test-Path -LiteralPath $field.Text)) { $dialog.SelectedPath = $field.Text }
        if ($dialog.ShowDialog() -eq 'OK') {
            if ($isOutput) {
                $name = $packName
                $candidate = Join-Path $dialog.SelectedPath $name; $number = 2
                while (Test-Path -LiteralPath $candidate) { $candidate = Join-Path $dialog.SelectedPath ($name+' - Generated '+$number); $number++ }
                $field.Text = $candidate
            } else { $field.Text = $dialog.SelectedPath }
        }
        $dialog.Dispose()
    })
    $hint = Label $Help 24 ($Y+59) 920 23; $hint.ForeColor = [Drawing.Color]::FromArgb(192,220,192)
}
Folder-Row 'aot' 'Aces of Thunder installation' 110 'Select the game folder containing aces.vromfs.bin and the high-quality cockpit content.'
Folder-Row 'il2' 'IL-2 Great Battles installation' 199 'Native shader and aircraft donors come from your local IL-2 install and JH 2.5 WT base.'
Folder-Row 'base' 'JH 2.5 WT base mod (newest WT N preferred)' 288 'Defaults to the highest-numbered JH_PR_2.5 Jungle Hawks - WT N in MODS. Its mesh, script and loadout fixes are retained.'
Folder-Row 'output' 'New output mod folder' 377 'Browse selects its parent folder. Creates a new inactive mod; existing folders and JSGME activation are preserved.'
$boxes['aot'].Text = Find-Game 'Aces of Thunder'
$boxes['il2'].Text = Find-Game 'IL-2 Sturmovik Battle of Stalingrad'
if ($boxes['il2'].Text) {
    $mods = Join-Path $boxes['il2'].Text 'MODS'
    $newest = @(Get-ChildItem -LiteralPath $mods -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $slots.base.folder_pattern } |
        Sort-Object { $n = [regex]::Match($_.Name,'(\d+(\.\d+)?)$').Value; if ($n -notmatch '\.') { $n += '.0' }; [version]$n } -Descending | Select-Object -First 1)
    if ($newest.Count) { $boxes['base'].Text = $newest[0].FullName }
    else { foreach ($name in @($slots.base.fallbacks)) {
        $candidate = Join-Path $mods $name
        if (Test-Path -LiteralPath $candidate) { $boxes['base'].Text = $candidate; break }
    } }
    $boxes['output'].Text = Join-Path $mods $packName
    if (Test-Path -LiteralPath $boxes['output'].Text) { $boxes['output'].Text += ' - Generated' }
}
$keep = New-Object Windows.Forms.CheckBox; $keep.Text = 'Keep extracted source files (for debugging)'; $keep.Checked = $false; $keep.SetBounds(24,468,600,26); $form.Controls.Add($keep)
$build = Button 'Build mod' 24 508 150 40
$open = Button 'Open output' 188 508 150 40; $open.Enabled = $false
$open.Add_Click({ if (Test-Path -LiteralPath $boxes['output'].Text) { Start-Process explorer.exe -ArgumentList ('"'+$boxes['output'].Text+'"') -WindowStyle Hidden } })
$status = Label 'Ready. First build downloads verified tools and a private Python runtime.' 355 515 590 34
$log = New-Object Windows.Forms.TextBox; $log.Multiline = $true; $log.ScrollBars = 'Vertical'; $log.ReadOnly = $true; $log.SetBounds(24,562,920,186)
$log.BackColor = [Drawing.Color]::FromArgb(9,16,11); $log.ForeColor = [Drawing.Color]::White; $log.Font = New-Object Drawing.Font('Consolas',9); $form.Controls.Add($log)
$timer = New-Object Windows.Forms.Timer; $timer.Interval = 1000
$timer.Add_Tick({
    $lines = @(); foreach ($file in @($script:runOut,$script:runErr)) { if (Test-Path -LiteralPath $file) { $lines += Get-Content -LiteralPath $file -Tail 130 -ErrorAction SilentlyContinue } }
    $log.Text = ($lines -join [Environment]::NewLine); $log.SelectionStart = $log.TextLength; $log.ScrollToCaret()
    if ($script:process) { $script:process.Refresh(); if ($script:process.HasExited) {
        $script:process.WaitForExit(); $code = $script:process.ExitCode; $timer.Stop(); $build.Enabled = $true
        foreach ($tb in $boxes.Values) { $tb.Enabled = $true }; $keep.Enabled = $true
        foreach ($button in $script:folderButtons) { $button.Enabled = $true }
        if ($code -eq 0) { $status.Text = 'Complete. Mod created inactive; enable it manually in JSGME.'; $open.Enabled = $true }
        else { $status.Text = 'Build failed. See the log; existing game/mod files were preserved.' }
        $script:process = $null
    } }
})
$build.Add_Click({
    try {
        foreach ($key in @('aot','il2','base','output')) { if ([string]::IsNullOrWhiteSpace($boxes[$key].Text)) { throw "Select the $key folder first." } }
        if (Test-Path -LiteralPath $boxes['output'].Text) { throw 'Output already exists. Choose a new folder; an existing mod will not be overwritten.' }
        $jobs = Join-Path $root '.jobs'; New-Item -ItemType Directory -Force -Path $jobs | Out-Null
        $id = [Guid]::NewGuid().ToString('N'); $cfg = Join-Path $jobs "$id.json"
        @{ aot=$boxes['aot'].Text; il2=$boxes['il2'].Text; base=$boxes['base'].Text; output=$boxes['output'].Text; keep_source=[bool]$keep.Checked } | ConvertTo-Json | Set-Content -LiteralPath $cfg -Encoding UTF8
        $script:runOut = Join-Path $jobs "$id.out.log"; $script:runErr = Join-Path $jobs "$id.err.log"
        $launchArgs = '-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $root 'Bootstrap.ps1')+'" -ConfigPath "'+$cfg+'"'
        $script:process = Start-Process powershell.exe -ArgumentList $launchArgs -WindowStyle Hidden -RedirectStandardOutput $script:runOut -RedirectStandardError $script:runErr -PassThru
        $build.Enabled = $false; $open.Enabled = $false; $keep.Enabled = $false; foreach ($tb in $boxes.Values) { $tb.Enabled = $false }
        foreach ($button in $script:folderButtons) { $button.Enabled = $false }
        $status.Text = 'Building. Source games are read-only; the completed mod stays inactive.'; $log.Text = 'Starting build...'; $timer.Start()
    } catch { [Windows.Forms.MessageBox]::Show($_.Exception.Message,'Cannot start build','OK','Warning') | Out-Null }
})
$form.Add_FormClosing({ if ($script:process -and !$script:process.HasExited) { $_.Cancel = $true; [Windows.Forms.MessageBox]::Show('The build is still running. Keep this window open until it finishes.','Build in progress') | Out-Null } })
# UI only: the mod's own loading-screen art as a banner; every control moves down by its height
$bannerPath = Join-Path $root 'art\banner.png'
if (Test-Path -LiteralPath $bannerPath) {
    $bannerH = 150
    foreach ($control in @($form.Controls)) { $control.Top += $bannerH }
    $form.ClientSize = New-Object Drawing.Size($form.ClientSize.Width,($form.ClientSize.Height + $bannerH))
    $form.MinimumSize = $form.Size
    $banner = New-Object Windows.Forms.PictureBox
    $banner.Image = [Drawing.Image]::FromFile($bannerPath); $banner.SizeMode = 'Zoom'
    $banner.SetBounds(0,0,$form.ClientSize.Width,$bannerH); $banner.BackColor = $form.BackColor
    $form.Controls.Add($banner)
}
if ($SelfTest) {
    if ($boxes.Count -ne 4) { throw 'Expected four folder fields' }
    if ($keep.Checked) { throw 'Keep-source option must default to off' }
    $form.CreateControl()
    foreach ($control in $form.Controls) {
        if ($control.Right -gt $form.ClientSize.Width -or $control.Bottom -gt $form.ClientSize.Height) { throw ('Control exceeds form bounds: '+$control.Text) }
        $control.CreateControl()
    }
    if ($PreviewPath) {
        $form.Show(); $form.Refresh(); [Windows.Forms.Application]::DoEvents()
        $bitmap = New-Object Drawing.Bitmap($form.Width,$form.Height)
        $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
        $bitmap.Save($PreviewPath,[Drawing.Imaging.ImageFormat]::Png); $bitmap.Dispose()
        $form.Hide()
    }
    Write-Output ('GUI SELF-TEST PASS: four folder fields, keep-source option (off), build controls, native layout within bounds. Default base: '+$boxes['base'].Text)
} else { [void]$form.ShowDialog() }
$timer.Dispose(); $form.Dispose()
