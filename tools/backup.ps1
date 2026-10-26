<#
.SYNOPSIS
    一键版本化备份：预检 -> 提交 -> 打标签 -> 推送双远端。

.DESCRIPTION
    除草小车项目的标准备份入口。把"改完代码随手 commit + 偶尔 push"变成
    一条固定流程：先做安全预检（大文件 / 密钥 / 忽略规则），再提交、打版本
    标签、推送 GitHub（可选同时推 Gitee）。

.PARAMETER Message
    提交信息。建议格式：<type>: <一句话>，type 取 feat/fix/docs/chore/test/refactor。
    省略则交互式询问。

.PARAMETER Tag
    可选版本标签，如 v0.1.1。会创建注解标签并一并推送。

.PARAMETER Both
    同时推送到 gitee 远端（默认只推 origin / GitHub）。

.PARAMETER DryRun
    只跑预检并展示将要提交的内容，不提交、不推送。

.PARAMETER Force
    跳过交互确认。

.EXAMPLE
    .\tools\backup.ps1 "fix: 修正 motor 死区判定"

.EXAMPLE
    .\tools\backup.ps1 "feat: 接入 FOMO 检测" -Tag v0.2.0 -Both

.EXAMPLE
    .\tools\backup.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Message = "",
    [string]$Tag = "",
    [switch]$Both,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$MaxFileMB = 50
$HardLimitMB = 100

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
} catch { }

function Resolve-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        'D:\AI\git\cmd\git.exe',
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe')
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Git\cmd\git.exe')
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

$script:Git = Resolve-Git
if (-not $script:Git) {
    Write-Host ""
    Write-Host "   [FAIL] 找不到 git.exe。请把 Git 的 cmd 目录加入 PATH，" -ForegroundColor Red
    Write-Host "          或修改本脚本 Resolve-Git 里的候选路径。" -ForegroundColor Red
    exit 1
}

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text" -ForegroundColor Cyan
}
function Write-Ok([string]$Text)   { Write-Host "   [OK]   $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "   [WARN] $Text" -ForegroundColor Yellow }
function Write-Info([string]$Text) { Write-Host "   $Text" -ForegroundColor Gray }
function Write-Fail([string]$Text) {
    Write-Host ""
    Write-Host "   [FAIL] $Text" -ForegroundColor Red
    exit 1
}

function Invoke-Git {
    param([string[]]$GitArgs, [switch]$AllowFail)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $script:Git -c core.quotepath=false @GitArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0 -and -not $AllowFail) {
        $text = ($out | ForEach-Object { "$_" }) -join "`n"
        Write-Fail ("git " + ($GitArgs -join ' ') + " 失败：`n$text")
    }
    return $out
}

Write-Host ""
Write-Host "  除草小车 · 版本化备份" -ForegroundColor White
Write-Host "  仓库：$RepoRoot" -ForegroundColor DarkGray

Write-Step "0/5 环境校验"
if (-not (Test-Path (Join-Path $RepoRoot '.git'))) {
    Write-Fail "不是 Git 仓库根目录：$RepoRoot"
}
Set-Location $RepoRoot

$branch = (Invoke-Git @('rev-parse','--abbrev-ref','HEAD')).Trim()
if ($branch -ne 'main') {
    Write-Warn2 "当前分支为 $branch，本流程按 main 设计"
} else {
    Write-Ok "分支 main"
}
$userName = (Invoke-Git @('config','user.name') -AllowFail)
if (-not $userName) { Write-Warn2 "未配置 git user.name" } else { Write-Ok "提交身份 $userName" }

Write-Step "1/5 收集改动"
$statusLines = @(Invoke-Git @('status','--porcelain'))
if ($statusLines.Count -eq 0 -and -not $Tag) {
    Write-Warn2 "工作区干净，且未指定 -Tag，没有可备份的内容"
    exit 0
}
foreach ($line in $statusLines) { Write-Info $line }
if ($statusLines.Count -eq 0) { Write-Info "(无文件改动，仅打标签)" }

Write-Step "2/5 暂存并预检"
Invoke-Git @('add','-A') | Out-Null
$staged = @(Invoke-Git @('diff','--cached','--name-only'))
Write-Ok ("暂存 " + $staged.Count + " 个文件")

$blocking = @()
$warnSize = @()
foreach ($f in $staged) {
    if (-not (Test-Path -LiteralPath $f)) { continue }
    $mb = (Get-Item -LiteralPath $f).Length / 1MB
    if ($mb -ge $HardLimitMB) { $blocking += ("$f ($([math]::Round($mb,1)) MB) 超过 GitHub 单文件 100 MB 硬限") }
    elseif ($mb -ge $MaxFileMB) { $warnSize += ("$f ($([math]::Round($mb,1)) MB)") }
}
if ($warnSize.Count -gt 0) {
    Write-Warn2 "以下文件偏大，确认是否应入库："
    foreach ($w in $warnSize) { Write-Info "  $w" }
}

$diffText = (Invoke-Git @('diff','--cached','-U0'))
$secretPatterns = @(
    @{ Name = '火山方舟 Ark Key'; Regex = 'ark-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}' },
    @{ Name = 'OpenAI/DeepSeek Key'; Regex = 'sk-[A-Za-z0-9]{20,}' },
    @{ Name = 'GitHub Token'; Regex = 'gh[pousr]_[A-Za-z0-9]{20,}' },
    @{ Name = '私钥文件'; Regex = 'BEGIN [A-Z ]*PRIVATE KEY' },
    @{ Name = '明文密码字段'; Regex = '(?i)(password|passwd|api[_-]?key)\s*[:=]\s*["'']?[^\s"'']{6,}' }
)
$hitSecret = $false
foreach ($p in $secretPatterns) {
    $m = $diffText | Select-String -Pattern $p.Regex -AllMatches
    if ($m) {
        $hitSecret = $true
        $blocking += ("疑似$($p.Name)：$($m[0].Line.Trim())")
    }
}
if ($hitSecret) { } else { Write-Ok "密钥扫描通过" }

if ($blocking.Count -gt 0) {
    Write-Host ""
    foreach ($b in $blocking) { Write-Host "   [BLOCK] $b" -ForegroundColor Red }
    Invoke-Git @('reset') -AllowFail | Out-Null
    Write-Fail "预检未通过，已撤销暂存。请处理后重跑。"
}

if ($DryRun) {
    Write-Step "3/5 试运行结束"
    Write-Info "以上为将要提交的内容，未做任何提交或推送。"
    Invoke-Git @('reset') -AllowFail | Out-Null
    exit 0
}

Write-Step "3/5 提交"
if ($staged.Count -eq 0) {
    Write-Info "无文件改动，跳过提交，直接打标签"
    $commit = (Invoke-Git @('log','-1','--pretty=%h %s')).Trim()
} else {
    if (-not $Message) {
        $Message = Read-Host "   提交信息（如 fix: 修正电机死区）"
    }
    if (-not $Message.Trim()) { Write-Fail "提交信息不能为空" }
    if ($Message -notmatch '^[a-zA-Z]+(\(.+\))?:\s*\S') {
        Write-Warn2 "提交信息未使用 <type>: <描述> 格式，仍继续"
    }
    Invoke-Git @('commit','-m',$Message) | Out-Null
    $commit = (Invoke-Git @('log','-1','--pretty=%h %s')).Trim()
    Write-Ok "已提交 $commit"
}

Write-Step "4/5 版本标签"
if ($Tag) {
    if ($Tag -notmatch '^v\d+\.\d+\.\d+$') { Write-Warn2 "标签建议使用 vX.Y.Z 格式" }
    $exists = Invoke-Git @('tag','-l',$Tag) -AllowFail
    if ($exists) {
        $tagCommit = (Invoke-Git @('rev-list','-n','1',$Tag) -AllowFail).Trim()
        $headCommit = (Invoke-Git @('rev-parse','HEAD') -AllowFail).Trim()
        if ($tagCommit -eq $headCommit) {
            Write-Warn2 "标签 $Tag 已存在且指向当前提交，直接复用并推送"
        } else {
            Write-Fail "标签 $Tag 已存在且指向其他提交（$tagCommit），请换一个版本号"
        }
    } else {
        Invoke-Git @('tag','-a',$Tag,'-m',$Tag) | Out-Null
        Write-Ok "已打标签 $Tag"
    }
} else {
    Write-Info "未指定 -Tag，跳过"
}

Write-Step "5/5 推送到远端"
$targets = @('origin')
if ($Both) { $targets += 'gitee' }
foreach ($remote in $targets) {
    $url = (Invoke-Git @('remote','get-url',$remote) -AllowFail)
    if (-not $url) { Write-Warn2 "远端 $remote 未配置，跳过"; continue }
    Write-Info "推送 $remote ($url)"
    if ($Tag) {
        Invoke-Git @('push',$remote,'main','--follow-tags') | Out-Null
    } else {
        Invoke-Git @('push',$remote,'main') | Out-Null
    }
    Write-Ok "$remote 已同步"
}

Write-Host ""
Write-Host "  备份完成" -ForegroundColor Green
Write-Info "提交：$commit"
if ($Tag) { Write-Info "标签：$Tag" }
Write-Info "远端：" + ($targets -join ', ')
Write-Host ""
