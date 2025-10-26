import shutil, errno
import os, fnmatch
import sys
import re
import argparse
import json
import xml.etree.ElementTree as ET

# Color codes for terminal output
class Colors:
    # Check if we're on Windows and colors are supported
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except:
            pass

    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def copyanything(src, dst):
    def ignore_patterns(path, names):
        # Ignore Visual Studio user-specific files and folders
        ignored = []
        for name in names:
            if name == '.vs' or name.endswith('.suo') or name.endswith('.user'):
                ignored.append(name)
        return ignored

    try:
        shutil.copytree(src, dst, ignore=ignore_patterns)
    except OSError as exc: # python >2.5
        if exc.errno in (errno.ENOTDIR, errno.EINVAL):
            shutil.copy(src, dst)
        else: raise

def findReplace(directory, find, replace, filePattern):
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for filename in fnmatch.filter(files, filePattern):
            filepath = os.path.join(path, filename)
            with open(filepath, encoding='utf-8') as f:
                s = f.read()
            s = s.replace(find, replace)
            with open(filepath, "w", encoding='utf-8') as f:
                f.write(s)
        for dir in dirs:
            findReplace(os.path.join(path, dir), find, replace, filePattern)

def renameFiles(directory, find, replace):
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for filename in fnmatch.filter(files, find + '.*'):
            filepath = os.path.join(path, filename)
            os.rename(filepath, os.path.join(path, replace) + '.' + filename.partition('.')[2])
        for dir in dirs:
            filepath = os.path.join(path, dir)
            if dir == find:
                os.rename(filepath, os.path.join(path, replace))
                renameFiles(os.path.join(path, replace), find, replace)
            else:
                renameFiles(filepath, find, replace)

def find_props_file(start_dir, filename):
    """Search for a props file in current dir and parents"""
    search_dir = os.path.abspath(start_dir)
    while True:
        props_path = os.path.join(search_dir, filename)
        if os.path.exists(props_path):
            return props_path
        parent = os.path.dirname(search_dir)
        if parent == search_dir:  # Reached root
            return None
        search_dir = parent

def parse_props_file(props_file, property_name):
    """Extract a property value from props file"""
    try:
        tree = ET.parse(props_file)
        root = tree.getroot()

        # Handle namespace
        ns = {'msbuild': 'http://schemas.microsoft.com/developer/msbuild/2003'}

        # Find PropertyGroup/PropertyName
        for prop_group in root.findall('.//msbuild:PropertyGroup', ns):
            prop = prop_group.find(f'.//msbuild:{property_name}', ns)
            if prop is not None and prop.text:
                return prop.text.strip()

        # Try without namespace (for files that might not have it)
        for prop_group in root.findall('.//PropertyGroup'):
            prop = prop_group.find(f'.//{property_name}')
            if prop is not None and prop.text:
                return prop.text.strip()

        return None
    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse {props_file}: {e}{Colors.ENDC}")
        return None

def get_broforce_path(repos_parent):
    """Get Broforce path from props files or prompt"""
    # Try LocalBroforcePath.props in repos parent
    local_props = find_props_file(repos_parent, 'LocalBroforcePath.props')
    if local_props:
        path = parse_props_file(local_props, 'BroforcePath')
        if path:
            print(f"{Colors.GREEN}Found Broforce path from LocalBroforcePath.props: {path}{Colors.ENDC}")
            return path

    # Try BroforceGlobal.props in repos parent
    global_props = os.path.join(repos_parent, 'BroforceGlobal.props')
    if os.path.exists(global_props):
        path = parse_props_file(global_props, 'BroforcePath')
        if path:
            print(f"{Colors.GREEN}Found Broforce path from BroforceGlobal.props: {path}{Colors.ENDC}")
            return path

    # Fallback: prompt user
    print(f"{Colors.WARNING}Could not find BroforcePath in props files.{Colors.ENDC}")
    print(f"{Colors.CYAN}Searched for:{Colors.ENDC}")
    print(f"  - LocalBroforcePath.props in: {repos_parent}")
    print(f"  - BroforceGlobal.props in: {repos_parent}")
    print()
    path = input("Enter Broforce installation path: ").strip()
    if not os.path.exists(path):
        print(f"{Colors.FAIL}Error: Path does not exist: {path}{Colors.ENDC}")
        sys.exit(1)
    return path

def get_bromaker_lib_path(repos_parent, broforce_path):
    """Get BroMakerLib path from props files or auto-detect"""
    # Try LocalBroforcePath.props
    local_props = find_props_file(repos_parent, 'LocalBroforcePath.props')
    if local_props:
        path = parse_props_file(local_props, 'BroMakerLibPath')
        if path and os.path.exists(path):
            print(f"{Colors.GREEN}Found BroMakerLib path from LocalBroforcePath.props{Colors.ENDC}")
            return path

    # Auto-detect: try local Bro-Maker repo first
    local_bromaker = os.path.join(repos_parent, "Bro-Maker", "BroMakerLib", "bin", "Debug", "BroMakerLib.dll")
    if os.path.exists(local_bromaker):
        print(f"{Colors.GREEN}Found local BroMakerLib at: {local_bromaker}{Colors.ENDC}")
        return local_bromaker

    # Fall back to installed version
    installed_bromaker = os.path.join(broforce_path, "Mods", "BroMaker", "BroMakerLib.dll")
    if os.path.exists(installed_bromaker):
        print(f"{Colors.GREEN}Found installed BroMakerLib in Mods folder{Colors.ENDC}")
        return installed_bromaker

    print(f"{Colors.WARNING}Warning: Could not find BroMakerLib.dll{Colors.ENDC}")
    print(f"  Tried: {local_bromaker}")
    print(f"  Tried: {installed_bromaker}")
    return None

# Parse command line arguments
parser = argparse.ArgumentParser(
    description='Create a new Broforce mod or bro project from templates',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog='''Examples:
  %(prog)s                     # Interactive mode
  %(prog)s -t mod -n "My Mod" -a "MyName"
  %(prog)s --type bro --name "Super Bro" --author "CoolDev"
  %(prog)s -t mod -n "My Mod" -a "MyName" -o "BroforceMods"  # Output to different repo
'''
)
parser.add_argument('-t', '--type', choices=['mod', 'bro'], help='Project type (mod or bro)')
parser.add_argument('-n', '--name', help='Name of the mod or bro')
parser.add_argument('-a', '--author', help='Author name')
parser.add_argument('-o', '--output-repo', help='Name of the repository to output to (defaults to current repo)')
args = parser.parse_args()

# Get the repository name dynamically based on script location
script_dir = os.path.dirname(os.path.abspath(__file__))
template_repo_dir = os.path.dirname(script_dir)  # Repository containing the templates
template_repo_name = os.path.basename(template_repo_dir)
repos_parent = os.path.dirname(template_repo_dir)

# Determine output repository
if args.output_repo:
    output_repo_name = args.output_repo
    print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")
else:
    # Interactive mode: always ask for repo
    print(f"\n{Colors.HEADER}Select output repository:{Colors.ENDC}")
    print(f"{Colors.CYAN}1.{Colors.ENDC} {template_repo_name} (current repository)")
    print(f"{Colors.CYAN}2.{Colors.ENDC} Enter another repository name")
    repo_choice = input("Enter your choice (1 or 2): ").strip()

    if repo_choice == "1":
        output_repo_name = template_repo_name
    elif repo_choice == "2":
        output_repo_name = input("Enter repository name: ").strip()
        if not output_repo_name:
            print(f"{Colors.FAIL}Error: Repository name cannot be empty.{Colors.ENDC}")
            sys.exit(1)
    else:
        print(f"{Colors.FAIL}Invalid choice. Please run the script again and enter 1 or 2.{Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")

# Get Broforce path from props files
broforce_path = get_broforce_path(repos_parent)

# Check if Broforce path exists
if not os.path.exists(broforce_path):
    print(f"{Colors.FAIL}Error: Broforce path does not exist: {broforce_path}{Colors.ENDC}")
    sys.exit(1)

# Get project type
if args.type:
    template_type = args.type
else:
    print(f"{Colors.HEADER}What would you like to create?{Colors.ENDC}")
    print(f"{Colors.CYAN}1.{Colors.ENDC} Mod")
    print(f"{Colors.CYAN}2.{Colors.ENDC} Bro")
    choice = input("Enter your choice (1 or 2): ").strip()

    if choice == "1":
        template_type = "mod"
    elif choice == "2":
        template_type = "bro"
    else:
        print(f"{Colors.FAIL}Invalid choice. Please run the script again and enter 1 or 2.{Colors.ENDC}")
        sys.exit(1)

# Set template parameters based on type
if template_type == "mod":
    template_type_title = "Mod"
    source_template_name = "Mod Template"
else:
    template_type_title = "Bro"
    source_template_name = "Bro Template"

# Get the name for the new template
if args.name:
    newName = args.name
else:
    newName = input(f'Enter {template_type} name:\n')

newNameWithUnderscore = newName.replace(' ', '_')
newNameNoSpaces = newName.replace(' ', '')

# Get the author name
if args.author:
    authorName = args.author
else:
    authorName = input('Enter author name (e.g., YourName):\n')

# Define paths
templatePath = os.path.join(template_repo_dir, source_template_name)
output_repo_path = os.path.join(repos_parent, output_repo_name)

# Check if output repository exists
if not os.path.exists(output_repo_path):
    print(f"{Colors.FAIL}Error: Output repository does not exist: {output_repo_path}{Colors.ENDC}")
    print(f"{Colors.WARNING}Please ensure the repository '{output_repo_name}' exists in: {repos_parent}{Colors.ENDC}")
    sys.exit(1)

# Copy BroforceModBuild.targets to output repo Scripts folder (if different repo)
if output_repo_path != template_repo_dir:
    output_scripts_dir = os.path.join(output_repo_path, 'Scripts')
    if not os.path.exists(output_scripts_dir):
        os.makedirs(output_scripts_dir)
        print(f"{Colors.GREEN}Created Scripts directory: {output_scripts_dir}{Colors.ENDC}")

    targets_source = os.path.join(script_dir, 'BroforceModBuild.targets')
    targets_dest = os.path.join(output_scripts_dir, 'BroforceModBuild.targets')

    if os.path.exists(targets_source):
        try:
            # Only copy if destination doesn't exist or is different
            if not os.path.exists(targets_dest):
                shutil.copy2(targets_source, targets_dest)
                print(f"{Colors.GREEN}Copied BroforceModBuild.targets to output repository{Colors.ENDC}")
            else:
                # Check if files are identical
                import filecmp
                if not filecmp.cmp(targets_source, targets_dest, shallow=False):
                    try:
                        shutil.copy2(targets_source, targets_dest)
                        print(f"{Colors.GREEN}Updated BroforceModBuild.targets in output repository{Colors.ENDC}")
                    except PermissionError:
                        print(f"{Colors.WARNING}Warning: Could not update BroforceModBuild.targets (file in use){Colors.ENDC}")
                else:
                    print(f"{Colors.BLUE}BroforceModBuild.targets already up-to-date{Colors.ENDC}")
        except PermissionError:
            print(f"{Colors.WARNING}Warning: Could not copy BroforceModBuild.targets (file in use){Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: BroforceModBuild.targets not found in template repo{Colors.ENDC}")

# Create the release folder structure in output repo
releasesPath = os.path.join(output_repo_path, 'Releases')
newReleaseFolder = os.path.join(releasesPath, newName)
newRepoPath = os.path.join(output_repo_path, newName)

# Check if template directory exists
if not os.path.exists(templatePath):
    print(f"{Colors.FAIL}Error: Template directory not found: {templatePath}{Colors.ENDC}")
    print(f"Please ensure the '{source_template_name}' directory exists in your repository.")
    sys.exit(1)

# Create Releases directory if it doesn't exist
if not os.path.exists(releasesPath):
    try:
        os.makedirs(releasesPath)
        print(f"{Colors.GREEN}Created Releases directory: {releasesPath}{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed to create Releases directory: {e}{Colors.ENDC}")
        sys.exit(1)

# Check if destination directories already exist
if os.path.exists(newReleaseFolder):
    print(f"{Colors.FAIL}Error: Release directory already exists: {newReleaseFolder}{Colors.ENDC}")
    print(f"Please choose a different {template_type} name or remove the existing directory.")
    sys.exit(1)

if os.path.exists(newRepoPath):
    print(f"{Colors.FAIL}Error: Repository directory already exists: {newRepoPath}{Colors.ENDC}")
    print(f"Please choose a different {template_type} name or remove the existing directory.")
    sys.exit(1)

try:
    # Create the release folder
    os.makedirs(newReleaseFolder)
    # Copy the source template to the repo
    copyanything(templatePath, newRepoPath)
except Exception as e:
    print(f"{Colors.FAIL}Error: Failed to copy template files: {e}{Colors.ENDC}")
    # Clean up partially created directories
    if os.path.exists(newReleaseFolder):
        shutil.rmtree(newReleaseFolder)
    if os.path.exists(newRepoPath):
        shutil.rmtree(newRepoPath)
    sys.exit(1)

try:
    # Rename files named with template name (with space)
    renameFiles(newRepoPath, source_template_name, newName)

    # Also rename files named without space
    if template_type == "mod":
        renameFiles(newRepoPath, 'ModTemplate', newNameNoSpaces)
    else:
        renameFiles(newRepoPath, 'BroTemplate', newNameNoSpaces)

    # File types to process
    if template_type == "mod":
        fileTypes = ["*.csproj", "*.cs", "*.sln", "*.json", "*.xml"]
    else:
        fileTypes = ["*.csproj", "*.cs", "*.sln", "*.json"]

    for fileType in fileTypes:
        # Replace template names
        findReplace(newRepoPath, source_template_name, newName, fileType)
        findReplace(newRepoPath, source_template_name.replace(' ', '_'), newNameWithUnderscore, fileType)
        if template_type == "mod":
            findReplace(newRepoPath, "ModTemplate", newNameNoSpaces, fileType)
        else:
            findReplace(newRepoPath, "BroTemplate", newNameNoSpaces, fileType)

        # Replace author placeholder
        findReplace(newRepoPath, "AUTHOR_NAME", authorName, fileType)

        # Replace repository URL with output repository name
        findReplace(newRepoPath, "REPO_NAME", output_repo_name, fileType)

    # Special handling for .csproj file references for Bros
    if template_type == "bro":
        findReplace(newRepoPath, "BroTemplate.cs", f"{newNameNoSpaces}.cs", "*.csproj")

        # Get BroMaker version from its Info.json
        bromaker_info_path = os.path.join(broforce_path, "Mods", "BroMaker", "Info.json")
        bromaker_version = "2.6.0"  # Default fallback version

        if os.path.exists(bromaker_info_path):
            try:
                with open(bromaker_info_path, 'r', encoding='utf-8') as f:
                    bromaker_info = json.load(f)
                    bromaker_version = bromaker_info.get('Version', bromaker_version)
                    print(f"{Colors.GREEN}Detected BroMaker version: {bromaker_version}{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.WARNING}Warning: Could not read BroMaker version from Info.json: {e}{Colors.ENDC}")
                print(f"{Colors.WARNING}Using default BroMaker version: {bromaker_version}{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}Warning: BroMaker Info.json not found at {bromaker_info_path}{Colors.ENDC}")
            print(f"Using default BroMaker version: {bromaker_version}")

        # Replace BroMaker version placeholder
        findReplace(newRepoPath, "BROMAKER_VERSION", bromaker_version, "*.json")

    # Create the Changelog.md file in the Releases folder
    changelogPath = os.path.join(newReleaseFolder, 'Changelog.md')
    changelogContent = '''## v1.0.0 (unreleased)
- Initial release
'''

    with open(changelogPath, 'w', encoding='utf-8') as changelogFile:
        changelogFile.write(changelogContent)

    print(f"\n{Colors.GREEN}{Colors.BOLD}Success! Created new {template_type} '{newName}'{Colors.ENDC}")
    if args.output_repo:
        print(f"{Colors.CYAN}Output repository:{Colors.ENDC} {output_repo_name}")
    print(f"{Colors.CYAN}Source files:{Colors.ENDC} {newRepoPath}")
    print(f"{Colors.CYAN}Releases folder:{Colors.ENDC} {newReleaseFolder}")
    print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
    print(f"  1. Open the project in Visual Studio")
    print(f"  2. Build the project (builds to game automatically)")
    print(f"  3. Launch Broforce to test your {template_type}")

except Exception as e:
    print(f"{Colors.FAIL}Error: Failed during file processing: {e}{Colors.ENDC}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
