# Broforce Templates

Templates and tools for creating Broforce mods and custom bros.

## Setup

Create a props file to configure paths for the build system.

### Option 1: LocalBroforcePath.props (per-repo)
Create this file in your repo's root directory:
```xml
<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <BroforcePath>C:\Program Files (x86)\Steam\steamapps\common\Broforce</BroforcePath>
    <!-- Point these to your installed mods (Thunderstore structure) -->
    <BroMakerLibPath>$(BroforcePath)\Mods\BroMaker-BroMaker\BroMaker\BroMakerLib.dll</BroMakerLibPath>
    <RocketLibPath>$(BroforcePath)\Mods\RocketLib-RocketLib\RocketLib\RocketLib.dll</RocketLibPath>
    <!-- If building from source repos: -->
    <!-- <BroMakerLibPath>C:\Users\YourName\repos\Bro-Maker\BroMakerLib\_ModContent\BroMakerLib.dll</BroMakerLibPath> -->
    <!-- <RocketLibPath>C:\Users\YourName\repos\RocketLib\RocketLib\_ModContent\RocketLib.dll</RocketLibPath> -->
  </PropertyGroup>
</Project>
```

### Option 2: BroforceGlobal.props (shared across repos)
Create this file in your repos parent directory with the same structure.

See `Scripts/LocalBroforcePath.example.props` and `Scripts/BroforceGlobal.example.props` for templates.

## broforce-tools

Tool for creating projects, setting up Thunderstore metadata, and packaging mods.

### Installation

**Windows/Other (pipx):**
```bash
pipx install path/to/Broforce-Templates/Scripts
```
Requires Python 3.9+. The templates directory is auto-detected from `repos_parent` config or `BROFORCE_TEMPLATES_DIR` env var.

**NixOS:**
```nix
# In flake.nix inputs
broforce-tools.url = "github:alexneargarder/Broforce-Templates?dir=Scripts";

# Enable in configuration
programs.broforce-tools.enable = true;
```

Both methods install `bt` and `broforce-tools` commands globally.

### Updating

**pipx:**
```bash
pipx install --force path/to/Broforce-Templates/Scripts
```

**NixOS:** Rebuild after updating flake inputs.

### Running the Tool

```bash
bt
```

Running without arguments opens interactive mode with a menu.

### Configuration

Run the setup wizard for first-time configuration:
```bash
bt config init
```

Or set values individually:
```bash
bt config set repos_parent D:\GitHub
bt config add-repo BroforceMods
bt config set defaults.namespace YourName
```

Config file location:
- **Windows:** `%APPDATA%\broforce-tools\config.json`
- **Linux/NixOS:** `~/.config/broforce-tools/config.json`

Config commands:
```bash
bt config show          # Print config path and contents
bt config path          # Print just the config file path
bt config edit          # Open config in $EDITOR
bt config set <key> <value>  # Set a value (empty string to clear)
bt config add-repo [name]    # Add a repo (auto-detects from cwd)
bt config remove-repo <name> # Remove a repo
bt config init          # Interactive setup wizard
```

Available config keys:
- `repos_parent` - Parent directory containing all repos
- `release_dir` - Central directory to copy release zips after packaging
- `templates_dir` - Path to Broforce-Templates repo (override for non-standard layouts)
- `defaults.namespace` - Pre-filled namespace for init-thunderstore
- `defaults.website_url` - Pre-filled URL for init-thunderstore

Additional config file keys (edit manually or via NixOS module):
- `repos` - Repositories to search for projects
- `ignore` - Per-repo lists of project names to hide from selection menus

### create

Create a new mod or bro project from templates.

```bash
# Interactive
bt create

# Command line
bt create -t mod -n "My Mod" -a "YourName"
bt create -t bro -n "My Bro" -a "YourName" -o "BroforceMods"
```

Options:
- `-t, --type` - Project type: `mod`, `bro`, or `wardrobe`
- `-n, --name` - Project name
- `-a, --author` - Author name
- `-o, --output-repo` - Target repository (defaults to current)

Creates source files, a Changelog.md in the release folder, and copies build targets to the output repo.

### init-thunderstore

Set up Thunderstore metadata for an existing project.

```bash
# Interactive (select from available projects)
bt init-thunderstore

# Specify project
bt init-thunderstore "Project Name"
```

Creates in the project's release folder:
- `manifest.json` - Package metadata with auto-detected dependencies
- `README.md` - Template readme
- `icon.png` - Placeholder icon (replace before publishing)
- `Changelog.md` - If not already present

Release folder structure is determined by project count: single-project repos use a flat `Release/` folder, multi-project repos use `Releases/{ProjectName}/`.

Dependencies are detected by scanning the project's .csproj for RocketLib/BroMakerLib references.

### package

Create a Thunderstore-ready ZIP package.

```bash
# Interactive (select from projects with metadata)
bt package

# Specify project
bt package "Project Name"

# Override version
bt package "Project Name" --version 2.0.0
```

The version is read from `Changelog.md` (looks for `## v1.0.0` or `## v1.0.0 (unreleased)`). The tool syncs this version to manifest.json and Info.json/.mod.json.

By default, the `(unreleased)` tag is removed from the source Changelog.md when packaging. Use `--keep-unreleased` to preserve it for test packages.

Output: `{Namespace}-{PackageName}-{Version}.zip` in the project's release folder.

### unreleased

List projects with unreleased changelog entries and optionally package them.

```bash
bt unreleased              # Current repo only
bt unreleased --all-repos  # All configured repos
```

### changelog

Manage project changelogs.

```bash
# Add entry (interactive project selection)
bt changelog add "Fixed spawn bug"

# Add entry to specific project
bt changelog add "Project Name" "Fixed spawn bug"

# Show latest entries
bt changelog show
bt changelog show "Project Name"

# Open in editor
bt changelog edit "Project Name"
```

### deps

Show dependency versions (cached from Thunderstore API).

```bash
bt deps              # Show cached versions
bt deps --refresh    # Force re-fetch from API
```

### Global Flags

- `--all-repos` - Show projects from all configured repos (not just current directory)
- `--clear-cache` - Clear the dependency version cache
- `--version` - Show tool version

## Building Projects

The build targets file (`BroforceModBuild.targets`) automatically:
- Detects project type (mod or bro) from metadata files
- Copies DLL to `_ModContent` folder
- Installs to game directory on build
- Optionally closes/launches Broforce

Build in Visual Studio or with MSBuild.

### Project Structure

```
ProjectName/
├── ProjectName/
│   ├── _ModContent/     # Metadata folder (name auto-detected)
│   │   ├── Info.json    # Mod metadata (mods)
│   │   └── *.mod.json   # Bro metadata (bros)
│   └── ProjectName.csproj
└── Release/             # Or Releases/ for multi-project repos
    └── ProjectName/     # Subdirectory only in multi-project repos
        ├── manifest.json
        ├── README.md
        ├── icon.png
        └── Changelog.md
```

The metadata folder can be named anything (`_ModContent`, `_Mod`, etc.) - the tool finds it by looking for `Info.json` or `*.mod.json`.

## Optional Setup

### Tab Completion

After installation, enable shell completion:

```bash
# PowerShell
bt --install-completion powershell

# Bash
bt --install-completion bash

# Zsh
bt --install-completion zsh

# Fish
bt --install-completion fish
```

Restart your shell after installing completion.
