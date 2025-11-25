# PowerShell tab completion for broforce-tools.py
# Add to your PowerShell profile: . "C:\Users\Alex\repos\Broforce-Templates\Scripts\broforce-tools-completion.ps1"

$script:broforcetoolsPath = "C:\Users\Alex\repos\Broforce-Templates\Scripts\broforce-tools.py"
$script:broforcetoolsCommands = @('create', 'init-thunderstore', 'package')
$script:broforcetoolsGlobalFlags = @('--all-repos', '--add-repo', '--clear-cache', '--help', '-h')
$script:createFlags = @('-t', '--template', '-n', '--name', '-a', '--author', '-o', '--output-repo', '--help', '-h')
$script:packageFlags = @('--version', '--help', '-h')
$script:initFlags = @('--help', '-h')

function Invoke-BroforceTools {
    param([string[]]$Arguments)
    try {
        $output = & python $script:broforcetoolsPath @Arguments 2>$null
        if ($output) {
            return $output -split "`n" | Where-Object { $_ -ne '' }
        }
    } catch {}
    return @()
}

Register-ArgumentCompleter -Native -CommandName @('broforce-tools', 'broforce-tools.py', 'bt') -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $tokens = $commandAst.ToString() -split '\s+'

    # Find the subcommand if any
    $subcommand = $null
    foreach ($token in $tokens[1..($tokens.Length-1)]) {
        if ($token -in $script:broforcetoolsCommands) {
            $subcommand = $token
            break
        }
    }

    # Determine what to complete
    $prevToken = if ($tokens.Length -gt 1) { $tokens[-2] } else { '' }

    # Complete flag values
    if ($prevToken -eq '-t' -or $prevToken -eq '--template') {
        return Invoke-BroforceTools @('--list-templates') | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
    }

    if ($prevToken -eq '-o' -or $prevToken -eq '--output-repo' -or $prevToken -eq '--add-repo') {
        return Invoke-BroforceTools @('--list-repos') | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
    }

    # Complete subcommands if none selected yet
    if (-not $subcommand) {
        $completions = @()

        # Add subcommands
        $completions += $script:broforcetoolsCommands | Where-Object { $_ -like "$wordToComplete*" }

        # Add global flags
        if ($wordToComplete -like '-*' -or $wordToComplete -eq '') {
            $completions += $script:broforcetoolsGlobalFlags | Where-Object {
                $_ -like "$wordToComplete*" -and $_ -notin $tokens
            }
        }

        return $completions | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
        }
    }

    # Complete based on subcommand
    $completions = @()

    switch ($subcommand) {
        'create' {
            if ($wordToComplete -like '-*') {
                $completions = $script:createFlags | Where-Object { $_ -like "$wordToComplete*" -and $_ -notin $tokens }
            }
        }
        'package' {
            if ($wordToComplete -like '-*') {
                $completions = $script:packageFlags | Where-Object { $_ -like "$wordToComplete*" -and $_ -notin $tokens }
            } else {
                $completions = Invoke-BroforceTools @('--list-projects', 'package') | Where-Object { $_ -like "$wordToComplete*" }
            }
        }
        'init-thunderstore' {
            if ($wordToComplete -like '-*') {
                $completions = $script:initFlags | Where-Object { $_ -like "$wordToComplete*" -and $_ -notin $tokens }
            } else {
                $completions = Invoke-BroforceTools @('--list-projects', 'init-thunderstore') | Where-Object { $_ -like "$wordToComplete*" }
            }
        }
    }

    # If no completions, return current word to prevent file path fallback
    if (-not $completions -or $completions.Count -eq 0) {
        if ($wordToComplete) {
            return [System.Management.Automation.CompletionResult]::new($wordToComplete, $wordToComplete, 'Text', 'No matches')
        }
        return @()
    }

    return $completions | ForEach-Object {
        $type = if ($_ -like '-*') { 'ParameterName' } else { 'ParameterValue' }
        # Quote values with spaces
        $completionText = if ($_ -match '\s') { "`"$_`"" } else { $_ }
        [System.Management.Automation.CompletionResult]::new($completionText, $_, $type, $_)
    }
}
