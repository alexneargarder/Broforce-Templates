# Broforce Templates

This repository provides templates and scripts for creating Broforce mods and custom bros.

## Setup

Create a props file in your repos parent directory to configure paths:

### Option 1: LocalBroforcePath.props (per-machine, git-ignored)
```xml
<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <BroforcePath>C:\Program Files (x86)\Steam\steamapps\common\Broforce</BroforcePath>
    <BroMakerLibPath>C:\Users\YourName\repos\Bro-Maker\BroMakerLib\_ModContent\BroMakerLib.dll</BroMakerLibPath>
    <RocketLibPath>C:\Users\YourName\repos\RocketLib\RocketLib\_ModContent\RocketLib.dll</RocketLibPath>
  </PropertyGroup>
</Project>
```

### Option 2: BroforceGlobal.props (shared settings)
Create this file in your repos parent directory with the same structure as above.

See `Scripts/LocalBroforcePath.example.props` and `Scripts/BroforceGlobal.example.props` for templates.

## Creating Projects

Use `create-project.py` to generate new mods or custom bros from the templates.

### Usage
```bash
# Interactive mode
python create-project.py

# Command line mode
python create-project.py -t mod -n "My Mod" -a "YourName"
python create-project.py --type bro --name "My Bro" --author "YourName"

# Create in a different repository
python create-project.py -t mod -n "My Mod" -a "YourName" -o "BroforceMods"
```

### Options
- `-h, --help` - Show help message
- `-t, --type` - Project type: `mod` or `bro`
- `-n, --name` - Project name
- `-a, --author` - Author name
- `-o, --output-repo` - Name of the repository to output to

The script will:
1. Create source files in the specified repository
2. Create a `Releases/[ProjectName]/` folder with Changelog.md
3. Copy `BroforceModBuild.targets` to the output repository's Scripts folder
4. Configure the project to use BroforceModBuild.targets

### Building Projects

The build targets file automatically:
- Detects project type (mod or bro)
- Copies DLL to `_ModContent` folder
- Installs to game directory on build
- Optionally closes/launches Broforce
- Supports hard links for faster builds

Build in Visual Studio or with MSBuild - everything is automatic!

### Releases Folder Structure

```
Releases/
└── ProjectName/
    └── Changelog.md    # Version history
```

The `_ModContent` folder in your project contains all mod/bro assets and gets installed to the game automatically on build.
