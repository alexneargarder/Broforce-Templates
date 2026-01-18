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

**NixOS:**
```nix
# In flake.nix inputs
broforce-tools.url = "github:alexneargarder/Broforce-Templates?dir=Scripts";

# Enable in configuration
programs.broforce-tools.enable = true;
```

Both methods install `bt` and `broforce-tools` commands globally.

### Running the Tool

```bash
bt
```

Running without arguments opens interactive mode with a menu.

### Configuration

Create a config file to configure repos and defaults:
- **Windows:** `Scripts/broforce-tools.json` (next to the script)
- **Linux/NixOS:** `~/.config/broforce-tools/config.json`
```json
{
  "repos": ["BroforceMods", "RocketLib", "Bro-Maker"],
  "ignore": {
    "BroforceMods": ["ExampleMod"]
  },
  "defaults": {
    "namespace": "YourName",
    "website_url": "https://github.com/yourname/repo"
  }
}
```

- `repos` - Repositories to search for projects
- `ignore` - Per-repo lists of project names to hide from selection menus
- `defaults.namespace` - Pre-filled namespace for init-thunderstore
- `defaults.website_url` - Pre-filled URL for init-thunderstore

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
- `-t, --type` - Project type: `mod` or `bro`
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

Output: `{Namespace}-{PackageName}-{Version}.zip` in the project's release folder.

### Global Flags

These work with any subcommand or standalone:

- `--all-repos` - Show projects from all configured repos (not just current directory)
- `--add-repo [NAME]` - Add a repo to the config (uses current repo if name omitted)
- `--clear-cache` - Clear the dependency version cache

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
