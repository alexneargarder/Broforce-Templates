# PowerShell tab completion for broforce-tools (bt)
# Add to your PowerShell profile: . "/path/to/broforce-tools-completion.ps1"

function _bt_get_projects {
    param([string]$Mode)
    try {
        $output = python3 -m broforce_tools.completion_helper $Mode 2>$null
        if ($output) {
            return ($output -split "`n" | Where-Object { $_ -ne '' })
        }
    } catch {}
    return @()
}

function _bt_complete_list {
    param(
        [string[]]$Candidates,
        [string]$WordToComplete,
        [string]$Type = 'ParameterValue'
    )
    $Candidates | Where-Object { $_ -like "$WordToComplete*" } | ForEach-Object {
        $text = if ($_ -match '\s') { "`"$_`"" } else { $_ }
        [System.Management.Automation.CompletionResult]::new($text, $_, $Type, $_)
    }
}

Register-ArgumentCompleter -Native -CommandName @('broforce-tools', 'bt') -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $tokens = $commandAst.ToString().Substring(0, $cursorPosition) -split '\s+'
    $tokenCount = $tokens.Count

    # If cursor is right after a space, we're completing a new (empty) token
    $astString = $commandAst.ToString().Substring(0, $cursorPosition)
    if ($astString.EndsWith(' ')) {
        $wordToComplete = ''
        $tokenCount++
    }

    $commands = @('create', 'init-thunderstore', 'package', 'unreleased', 'changelog', 'config', 'deps')
    $globalFlags = @('--help', '-h', '--clear-cache', '--version')

    # Position 1: complete commands and global flags
    if ($tokenCount -le 2) {
        _bt_complete_list -Candidates ($commands + $globalFlags) -WordToComplete $wordToComplete -Type 'ParameterName'
        return
    }

    $subcommand = $tokens[1]
    $prev = $tokens[$tokenCount - 2]

    switch ($subcommand) {
        'create' {
            if ($prev -eq '-t' -or $prev -eq '--type') {
                _bt_complete_list @('mod', 'bro', 'wardrobe') $wordToComplete
            } elseif ($prev -eq '-o' -or $prev -eq '--output-repo') {
                _bt_complete_list (_bt_get_projects 'repos') $wordToComplete
            } elseif ($wordToComplete -like '-*') {
                $flags = @('-t', '--type', '-n', '--name', '-a', '--author', '-o', '--output-repo',
                           '-y', '--non-interactive', '--no-thunderstore', '--help')
                _bt_complete_list $flags $wordToComplete 'ParameterName'
            }
        }
        'init-thunderstore' {
            if ($wordToComplete -like '-*') {
                $flags = @('-y', '--non-interactive', '-n', '--namespace', '-d', '--description',
                           '-w', '--website-url', '-p', '--package-name', '--all-repos', '--help')
                _bt_complete_list $flags $wordToComplete 'ParameterName'
            } else {
                _bt_complete_list (_bt_get_projects 'init') $wordToComplete
            }
        }
        'package' {
            if ($prev -eq '--version' -or $prev -eq '--package') {
                return
            } elseif ($wordToComplete -like '-*') {
                $flags = @('-y', '--non-interactive', '--version', '--all-repos',
                           '--allow-outdated-changelog', '--overwrite', '--update-deps',
                           '--no-update-deps', '--add-missing-deps', '--no-add-missing-deps',
                           '--keep-unreleased', '--help')
                _bt_complete_list $flags $wordToComplete 'ParameterName'
            } else {
                _bt_complete_list (_bt_get_projects 'package') $wordToComplete
            }
        }
        'unreleased' {
            if ($prev -eq '--package') {
                _bt_complete_list (_bt_get_projects 'package') $wordToComplete
            } elseif ($wordToComplete -like '-*') {
                $flags = @('-y', '--non-interactive', '--all-repos', '--package-all', '--package', '--help')
                _bt_complete_list $flags $wordToComplete 'ParameterName'
            }
        }
        'deps' {
            if ($wordToComplete -like '-*') {
                $flags = @('-r', '--refresh', '--help')
                _bt_complete_list $flags $wordToComplete 'ParameterName'
            }
        }
        'changelog' {
            # Position 2: complete changelog subcommands
            if ($tokenCount -le 3) {
                _bt_complete_list @('add', 'show', 'edit', '--help') $wordToComplete 'ParameterName'
            } else {
                $changelogSub = $tokens[2]
                if ($changelogSub -in @('add', 'show', 'edit')) {
                    if ($wordToComplete -like '-*') {
                        $flags = @('-y', '--non-interactive', '--all-repos', '--help')
                        _bt_complete_list $flags $wordToComplete 'ParameterName'
                    } else {
                        _bt_complete_list (_bt_get_projects 'package') $wordToComplete
                    }
                }
            }
        }
        'config' {
            if ($tokenCount -le 3) {
                _bt_complete_list @('show', 'path', 'edit', 'set', 'add-repo', 'remove-repo', 'init', '--help') $wordToComplete 'ParameterName'
            } else {
                $configSub = $tokens[2]
                switch ($configSub) {
                    'set' {
                        if ($tokenCount -le 4) {
                            $keys = @('repos_parent', 'release_dir', 'templates_dir', 'defaults.namespace', 'defaults.website_url')
                            _bt_complete_list $keys $wordToComplete
                        }
                    }
                    'init' {
                        if ($wordToComplete -like '-*') {
                            _bt_complete_list @('-y', '--non-interactive', '--help') $wordToComplete 'ParameterName'
                        }
                    }
                }
            }
        }
    }
}
