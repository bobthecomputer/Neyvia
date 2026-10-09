param(
    [string]$BaseUrl = 'http://127.0.0.1:8877',
    [string]$OutputDirectory = 'proof/ui-review-20260923/session-ui',
    [string]$LayaCli = 'C:\Users\user\Documents\Codex\2026-09-20\laya-c-est-l-alternative-open\outputs\laya-improvement-kit\skills\laya-autonomy\scripts\laya_autonomy.py'
)

$ErrorActionPreference = 'Stop'
$output = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDirectory))
New-Item -ItemType Directory -Path $output -Force | Out-Null

function Expect($kind, $value, $selector) {
    $entry = @{ kind = $kind }
    if ($null -ne $value) { $entry.value = $value }
    if ($null -ne $selector) { $entry.selector = $selector }
    return $entry
}

function Click($label, $expectations) {
    return @{ kind = 'click'; label = $label; side_effect = 'reversible'; timeout_ms = 8000; expectations = @($expectations) }
}

$chrome = Expect 'selector_exists' $null '.neyvia-session-chrome'
$cases = @(
    @{
        name = 'agent-idle'; query = 'surface=agent'; actions = @();
        expectations = @($chrome, (Expect 'selector_exists' $null '.neyvia-update-shortcut'),
            (Expect 'selector_absent' $null '.neyvia-task-continuity'),
            (Expect 'text_present' 'Start a conversation' $null))
    },
    @{
        name = 'device-details'; query = 'surface=agent';
        actions = @((Click 'Device control unverified. Show device details' @(
            (Expect 'selector_exists' $null '#neyvia-work-location'),
            (Expect 'text_present' 'No live control receipt' $null),
            (Expect 'selector_exists' $null "[data-laya-capability='ready']"))));
        expectations = @((Expect 'selector_exists' $null '#neyvia-work-location'),
            (Expect 'text_present' 'Run files' $null),
            (Expect 'text_present' 'Named navigation ready' $null))
    },
    @{
        name = 'computer-use-route'; query = 'surface=agent';
        actions = @(
            (Click 'Device control unverified. Show device details' @((Expect 'selector_exists' $null '#neyvia-work-location'))),
            (Click 'Open computer use' @((Expect 'selector_absent' $null '#neyvia-work-location')))
        );
        expectations = @((Expect 'selector_absent' $null '#neyvia-work-location'),
            (Expect 'text_present' 'Computer Use proof' $null))
    },
    @{
        name = 'prompt-editor'; query = 'surface=agent';
        actions = @((Click 'Edit system prompt' @((Expect 'selector_exists' $null "dialog[open][aria-label='Edit system prompts']"))));
        expectations = @((Expect 'selector_exists' $null '#neyvia-prompt-editor-content'),
            (Expect 'text_present' 'Chat system prompt' $null))
    },
    @{
        name = 'prompt-role'; query = 'surface=agent';
        actions = @(
            (Click 'Edit system prompt' @((Expect 'selector_exists' $null "dialog[open][aria-label='Edit system prompts']"))),
            (Click 'Planner' @((Expect 'text_present' 'Planner system prompt' $null)))
        );
        expectations = @((Expect 'selector_exists' $null '#neyvia-prompt-editor-content'),
            (Expect 'text_present' 'Planner system prompt' $null))
    },
    @{
        name = 'update-settings'; query = 'surface=agent';
        actions = @((Click 'Open app update settings' @((Expect 'url_contains' 'settingsTab=updates' $null))));
        expectations = @((Expect 'url_contains' 'settingsTab=updates' $null),
            (Expect 'text_present' 'Neyvia updates' $null))
    },
    @{
        name = 'update-check'; query = 'surface=settings&settingsTab=updates';
        ready = @((Expect 'selector_exists' $null '[data-settings-app-update-action="check"]'),
            (Expect 'text_present' 'Neyvia updates' $null));
        actions = @((Click 'Check' @((Expect 'selector_exists' $null "[data-app-update-status='ready'],[data-app-update-status='updated'],[data-app-update-status='failed']"))));
        expectations = @((Expect 'selector_exists' $null "[data-app-update-status='ready'],[data-app-update-status='updated'],[data-app-update-status='failed']"),
            (Expect 'text_present' 'Last checked' $null))
    },
    @{
        name = 'builder-idle'; query = 'surface=builder'; actions = @();
        expectations = @($chrome, (Expect 'text_present' 'Start an orchestration' $null))
    },
    @{
        name = 'state-walk'; query = 'surface=agent';
        actions = @(
            (Click 'Device control unverified. Show device details' @((Expect 'selector_exists' $null '#neyvia-work-location'))),
            (Click 'Close device details' @((Expect 'selector_absent' $null '#neyvia-work-location'))),
            (Click 'Edit system prompt' @((Expect 'selector_exists' $null "dialog[open][aria-label='Edit system prompts']"))),
            (Click 'Close prompt editor' @((Expect 'selector_absent' $null "dialog[open][aria-label='Edit system prompts']"))),
            (Click 'Open app update settings' @((Expect 'url_contains' 'settingsTab=updates' $null)))
        );
        expectations = @((Expect 'url_contains' 'settingsTab=updates' $null),
            (Expect 'text_present' 'Neyvia updates' $null))
    }
)

$ledger = @()
foreach ($case in $cases) {
    $request = @{
        manifest = @{
            url = "$BaseUrl/control?$($case.query)"
            goal = "Verify Neyvia $($case.name) controls and capture their rendered state."
            ready_expectations = @(if ($case.ready) { $case.ready } else { $chrome })
            ready_timeout_ms = 20000
            required_actions = @($case.actions)
            expectations = @($case.expectations)
            max_steps = [Math]::Max(1, $case.actions.Count)
            capture_screenshot = $true
        }
        approval = $true
    }
    $requestPath = Join-Path $output "$($case.name)-request.json"
    $receiptPath = Join-Path $output "$($case.name)-receipt.json"
    $imagePath = Join-Path $output "$($case.name).jpg"
    [System.IO.File]::WriteAllText($requestPath, ($request | ConvertTo-Json -Depth 15), (New-Object System.Text.UTF8Encoding($false)))
    $sha = ''
    $attempt = 0
    $totalElapsedMs = 0
    do {
        $attempt++
        & python $LayaCli browser --request $requestPath --output $receiptPath | Out-Null
        $exitCode = $LASTEXITCODE
        $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        $totalElapsedMs += [double]$receipt.receipt.elapsed_ms
        if ($receipt.receipt.screenshot -and (Test-Path -LiteralPath $receipt.receipt.screenshot)) {
            Copy-Item -LiteralPath $receipt.receipt.screenshot -Destination $imagePath -Force
            $sha = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    } while ($receipt.passed -and -not $sha -and $attempt -lt 3)
    if (-not $sha -and (Test-Path -LiteralPath $imagePath)) {
        Remove-Item -LiteralPath $imagePath -Force
    }
    $ledger += [pscustomobject]@{
        name = $case.name
        status = $receipt.status
        passed = $receipt.passed
        exitCode = $exitCode
        steps = $receipt.receipt.steps
        modelCalls = $receipt.receipt.model_calls
        elapsedMs = $receipt.receipt.elapsed_ms
        totalElapsedMs = [Math]::Round($totalElapsedMs, 3)
        attempts = $attempt
        screenshotError = $receipt.receipt.screenshot_error
        screenshotMethod = $receipt.receipt.screenshot_method
        screenshot = if ($sha) { $imagePath } else { '' }
        sha256 = $sha
        unmet = @($receipt.receipt.unmet_expectations)
    }
    Write-Output "$($case.name) $($receipt.status) steps=$($receipt.receipt.steps) elapsedMs=$($receipt.receipt.elapsed_ms) screenshot=$([bool]$sha)"
}
$ledgerPath = Join-Path $output 'ledger.json'
[System.IO.File]::WriteAllText($ledgerPath, ($ledger | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding($false)))
if (@($ledger | Where-Object { -not $_.passed -or -not $_.sha256 }).Count) { throw "Laya UI packet has failures: $ledgerPath" }
