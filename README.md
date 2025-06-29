# Broforce Templates

This repository provides templates and scripts for creating Broforce mods and custom bros.

## Setup
Set these environment variables:
- `BROFORCEPATH` - Path to your Broforce installation (e.g., `C:\Program Files (x86)\Steam\steamapps\common\Broforce`)
- `REPOSPATH` - Path to your repositories folder (the folder which contains this folder)

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
python create-project.py --type bro --name "My Bro" --author "YourName" --output-repo "MyOtherRepo"
```

### Options
- `-h, --help` - Show help message
- `-t, --type` - Project type: `mod` or `bro`
- `-n, --name` - Project name
- `-a, --author` - Author name
- `-o, --output-repo` - Name of the repository to output to (defaults to current repo)

The script will:
1. Create source files in the specified repository (or current repo if not specified)
2. Create release files in `Releases/[ProjectName]/` within the output repository
3. Generate a Changelog.txt
4. Configure BroMakerLib references (for bro projects)

When using the `-o` flag, the script will use templates from this repository but create all output files in the specified repository. This allows you to keep templates separate from your actual mod projects.

**Note:** The output repository must have the required build scripts in its `Scripts` folder:
- `bro-pre-build.bat` and `bro-post-build.bat` (for bro projects)
- `mod-pre-build.bat` and `mod-post-build.bat` (for mod projects)

These scripts are referenced by the generated .csproj files and are necessary for building the projects.

Run `CREATE LINKS.bat` in the Releases folder to create symlinks to your mods.
