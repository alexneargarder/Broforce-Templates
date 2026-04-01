"""Template file operations and props file parsing."""
import errno
import fnmatch
import os
import shutil
import stat
import xml.etree.ElementTree as ET
from typing import Optional

from .colors import Colors



def _make_writable(path: str) -> None:
    """Make all files and directories in a tree writable."""
    # Make the root directory writable first
    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
    for root, dirs, files in os.walk(path):
        for d in dirs:
            dir_path = os.path.join(root, d)
            os.chmod(dir_path, os.stat(dir_path).st_mode | stat.S_IWUSR)
        for f in files:
            file_path = os.path.join(root, f)
            os.chmod(file_path, os.stat(file_path).st_mode | stat.S_IWUSR)


def copyanything(src: str, dst: str) -> None:
    """Copy directory tree, ignoring VS user-specific files."""
    def ignore_patterns(path, names):
        ignored = []
        for name in names:
            if name == '.vs' or name.endswith('.suo') or name.endswith('.user'):
                ignored.append(name)
        return ignored

    try:
        shutil.copytree(src, dst, ignore=ignore_patterns, dirs_exist_ok=True)
        _make_writable(dst)
    except OSError as exc:
        if exc.errno in (errno.ENOTDIR, errno.EINVAL):
            shutil.copy(src, dst)
            os.chmod(dst, os.stat(dst).st_mode | stat.S_IWUSR)
        else:
            raise


def find_replace(directory: str, find: str, replace: str, file_pattern: str) -> None:
    """Find and replace text in files matching pattern."""
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for filename in fnmatch.filter(files, file_pattern):
            filepath = os.path.join(path, filename)
            with open(filepath, encoding='utf-8') as f:
                s = f.read()
            s = s.replace(find, replace)
            with open(filepath, "w", encoding='utf-8') as f:
                f.write(s)


def rename_files(directory: str, find: str, replace: str) -> None:
    """Rename files and directories matching pattern."""
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for filename in fnmatch.filter(files, find + '.*'):
            filepath = os.path.join(path, filename)
            os.rename(filepath, os.path.join(path, replace) + '.' + filename.partition('.')[2])
        for dir in dirs:
            filepath = os.path.join(path, dir)
            if dir == find:
                os.rename(filepath, os.path.join(path, replace))
                rename_files(os.path.join(path, replace), find, replace)
            else:
                rename_files(filepath, find, replace)


def find_props_file(start_dir: str, filename: str) -> Optional[str]:
    """Search for a props file in current dir and parents."""
    search_dir = os.path.abspath(start_dir)
    while True:
        props_path = os.path.join(search_dir, filename)
        if os.path.exists(props_path):
            return props_path
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            return None
        search_dir = parent


def parse_props_file(props_file: str, property_name: str) -> Optional[str]:
    """Extract a property value from props file."""
    try:
        tree = ET.parse(props_file)
        root = tree.getroot()

        ns = {'msbuild': 'http://schemas.microsoft.com/developer/msbuild/2003'}

        for prop_group in root.findall('.//msbuild:PropertyGroup', ns):
            prop = prop_group.find(f'.//msbuild:{property_name}', ns)
            if prop is not None and prop.text:
                return prop.text.strip()

        for prop_group in root.findall('.//PropertyGroup'):
            prop = prop_group.find(f'.//{property_name}')
            if prop is not None and prop.text:
                return prop.text.strip()

        return None
    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse {props_file}: {e}{Colors.ENDC}")
        return None


def get_broforce_path(repos_parent: str) -> Optional[str]:
    """Get Broforce path from props files."""
    import questionary
    import typer

    local_props = find_props_file(repos_parent, 'LocalBroforcePath.props')
    if local_props:
        path = parse_props_file(local_props, 'BroforcePath')
        if path:
            print(f"{Colors.GREEN}Found Broforce path from LocalBroforcePath.props: {path}{Colors.ENDC}")
            return path

    global_props = os.path.join(repos_parent, 'BroforceGlobal.props')
    if os.path.exists(global_props):
        path = parse_props_file(global_props, 'BroforcePath')
        if path:
            print(f"{Colors.GREEN}Found Broforce path from BroforceGlobal.props: {path}{Colors.ENDC}")
            return path

    print(f"{Colors.WARNING}Could not find BroforcePath in props files.{Colors.ENDC}")
    print(f"{Colors.CYAN}Searched for:{Colors.ENDC}")
    print(f"  - LocalBroforcePath.props in: {repos_parent}")
    print(f"  - BroforceGlobal.props in: {repos_parent}")
    print()
    path = questionary.text("Enter Broforce installation path:").ask()
    if not path:
        raise typer.Exit()
    if not os.path.exists(path):
        print(f"{Colors.FAIL}Error: Path does not exist: {path}{Colors.ENDC}")
        raise typer.Exit(1)
    return path


def get_bromaker_lib_path(repos_parent: str, broforce_path: str) -> Optional[str]:
    """Get BroMakerLib path from props files or auto-detect."""
    local_props = find_props_file(repos_parent, 'LocalBroforcePath.props')
    if local_props:
        path = parse_props_file(local_props, 'BroMakerLibPath')
        if path and os.path.exists(path):
            print(f"{Colors.GREEN}Found BroMakerLib path from LocalBroforcePath.props{Colors.ENDC}")
            return path

    local_bromaker = os.path.join(repos_parent, "Bro-Maker", "BroMakerLib", "bin", "Debug", "BroMakerLib.dll")
    if os.path.exists(local_bromaker):
        print(f"{Colors.GREEN}Found local BroMakerLib at: {local_bromaker}{Colors.ENDC}")
        return local_bromaker

    installed_bromaker = os.path.join(broforce_path, "Mods", "BroMaker", "BroMakerLib.dll")
    if os.path.exists(installed_bromaker):
        print(f"{Colors.GREEN}Found installed BroMakerLib in Mods folder{Colors.ENDC}")
        return installed_bromaker

    print(f"{Colors.WARNING}Warning: Could not find BroMakerLib.dll{Colors.ENDC}")
    print(f"  Tried: {local_bromaker}")
    print(f"  Tried: {installed_bromaker}")
    return None


