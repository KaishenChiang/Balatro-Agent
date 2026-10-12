# Pure prompt/link construction. This file never starts a client or a game.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'localization.ps1')

function Get-BalatroPlayPrompt([string]$ProjectRoot, [switch]$InlineRules,
        [string]$DeckKey = 'b_red', [string]$StakeChoice = 'white',
        [ValidateSet('en','zh-CN')][string]$Language = 'zh-CN') {
    $directory = [IO.Path]::GetFullPath($ProjectRoot)
    if (-not [IO.Directory]::Exists($directory)) { throw 'The project directory is unavailable.' }
    $portablePath = $directory.Replace('\', '/').TrimEnd('/')
    $rulesFile = if ($Language -eq 'en') { 'bootstrap.en.md' } else { 'bootstrap.md' }
    $choices = Get-BalatroPlayChoices
    $deck = @($choices.Decks | Where-Object { $_.Key -eq $DeckKey })
    $stake = @($choices.Stakes | Where-Object { $_.Key -eq $StakeChoice })
    if ($deck.Count -ne 1 -or $stake.Count -ne 1) { throw 'Select an original deck and a supported stake or mode.' }
    if ($Language -eq 'en') {
        $mode = switch ($stake[0].Key) {
            'highest' { 'Play one run at this deck''s highest verified unlocked stake.' }
            'climb' { 'Start at this deck''s highest verified unlocked stake; report and review normal losses, then retry the same stake with no retry limit. Recheck unlocks after wins and advance to the immediately next stake. Stop after beating Gold or when I ask to stop. Faults and UNKNOWN must not trigger retries.' }
            default { 'Play one run; do not retry automatically.' }
        }
        return 'Project directory: ' + $portablePath + [Environment]::NewLine +
            'Read this project''s prompts/' + $rulesFile + ', then first use balatro-agent MCP launch_game to open or show the game and play a native random run. Reply in English. If rules or MCP tools are unavailable, report the gap and stop.' + [Environment]::NewLine +
            'Selected deck: ' + $deck[0].EnglishName + '; selected stake / mode: ' + $stake[0].EnglishName + '.' + [Environment]::NewLine + $mode
    } else {
        $mode = switch ($stake[0].Key) {
            'highest' { '使用该牌组已核验解锁的最高注级，只尝试一局。' }
            'climb' { '从该牌组已核验解锁的最高注级开始；正常失败后报告、复盘并重试当前注级，不设正常败局重试次数上限；获胜后核验解锁，升到紧接的下一注级，直到金注通关或我叫停。故障和 UNKNOWN 不触发重试。' }
            default { '只游玩一局，不自动重试。' }
        }
        return '项目目录：' + $portablePath + [Environment]::NewLine +
            '请读取该项目的 prompts/' + $rulesFile + '，先通过 balatro-agent MCP 的 launch_game 打开或显示游戏，再按规则自主游玩原生随机对局。若无法读取规则或缺少 MCP 工具，报告缺项并停止。' + [Environment]::NewLine +
            '所选牌组：' + $deck[0].Name + '；所选注级／模式：' + $stake[0].Name + '。' + [Environment]::NewLine + $mode
    }
}

function Get-BalatroCodexLink([string]$ProjectRoot, [string]$Prompt) {
    $directory = [IO.Path]::GetFullPath($ProjectRoot)
    if (-not [IO.Directory]::Exists($directory) -or [string]::IsNullOrWhiteSpace($Prompt)) {
        throw 'A local project directory and prompt are required.'
    }
    # Encode each query value separately: spaces, Unicode, &, # and % remain data.
    return 'codex://threads/new?path=' + [Uri]::EscapeDataString($directory) +
        '&prompt=' + [Uri]::EscapeDataString($Prompt)
}
