"""Template operations for creating and managing projects."""
import errno
import fnmatch
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from .colors import Colors
from .config import get_configured_repos, get_ignored_projects
from .paths import get_repos_parent, get_templates_dir, is_windows


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
    except OSError as exc:
        if exc.errno in (errno.ENOTDIR, errno.EINVAL):
            shutil.copy(src, dst)
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
        for dir in dirs:
            find_replace(os.path.join(path, dir), find, replace, file_pattern)


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


def get_source_directory(project_path: str) -> Optional[str]:
    """Get the actual source directory containing _ModContent.

    Handles both flat and nested project structures:
    - Flat: ProjectName/_ModContent/ → returns ProjectName/
    - Nested: ProjectName/ProjectName/_ModContent/ → returns ProjectName/ProjectName/
    """
    if os.path.exists(os.path.join(project_path, '_ModContent')):
        return project_path

    project_name = os.path.basename(project_path)
    nested_path = os.path.join(project_path, project_name)
    if os.path.exists(os.path.join(nested_path, '_ModContent')):
        return nested_path

    return None


def detect_project_type(project_path: str) -> Optional[str]:
    """Detect if project is a mod or bro."""
    source_dir = get_source_directory(project_path)
    if not source_dir:
        return None

    mod_content_path = os.path.join(source_dir, '_ModContent')

    if os.path.exists(os.path.join(mod_content_path, 'Info.json')):
        return 'mod'

    try:
        for file in os.listdir(mod_content_path):
            if file.endswith('.mod.json'):
                return 'bro'
    except (OSError, FileNotFoundError):
        return None

    return None


def detect_current_repo(repos_parent: str) -> Optional[str]:
    """Detect which repo we're currently in based on cwd."""
    cwd = os.getcwd()

    cwd_original = os.path.abspath(cwd).replace('\\', '/')
    repos_original = os.path.abspath(repos_parent).replace('\\', '/')

    cwd_abs = cwd_original.lower()
    repos_abs = repos_original.lower()

    cwd_abs_alt = None
    repos_abs_alt = None

    if cwd_abs.startswith('c:/'):
        cwd_abs = '/mnt/c/' + cwd_abs[3:]
    elif cwd_abs.startswith('/mnt/c/'):
        cwd_abs_alt = 'c:/' + cwd_abs[7:]

    if repos_abs.startswith('c:/'):
        repos_abs = '/mnt/c/' + repos_abs[3:]
    elif repos_abs.startswith('/mnt/c/'):
        repos_abs_alt = 'c:/' + repos_abs[7:]

    cwd_orig_normalized = cwd_original.lower()
    if cwd_orig_normalized.startswith('c:/'):
        cwd_orig_normalized = '/mnt/c/' + cwd_orig_normalized[3:]

    repos_orig_normalized = repos_original.lower()
    if repos_orig_normalized.startswith('c:/'):
        repos_orig_normalized = '/mnt/c/' + repos_orig_normalized[3:]

    try:
        is_inside = False
        rel_path_lower = None
        rel_path_original = None

        if cwd_abs.startswith(repos_abs):
            is_inside = True
            rel_path_lower = cwd_abs[len(repos_abs):].lstrip('/')
            if cwd_orig_normalized.startswith(repos_orig_normalized):
                rel_path_original = cwd_original[len(repos_original):].lstrip('/')
        elif cwd_abs_alt and repos_abs_alt and cwd_abs_alt.startswith(repos_abs_alt):
            is_inside = True
            rel_path_lower = cwd_abs_alt[len(repos_abs_alt):].lstrip('/')
            rel_path_original = cwd_original[len(repos_original):].lstrip('/')

        if not is_inside or not rel_path_lower:
            return None

        if rel_path_original:
            repo_name = rel_path_original.split('/')[0]
        else:
            repo_name = rel_path_lower.split('/')[0]

        if not repo_name:
            return None

        try:
            actual_dirs = os.listdir(repos_parent)
            for dir_name in actual_dirs:
                if dir_name.lower() == repo_name.lower():
                    repo_path = os.path.join(repos_parent, dir_name)
                    if os.path.isdir(repo_path):
                        return dir_name
        except (OSError, FileNotFoundError):
            pass

        return None
    except (ValueError, OSError):
        return None


def find_projects(
    repos_parent: str,
    repos: list[str],
    require_metadata: bool = False,
    exclude_with_metadata: bool = False
) -> list[tuple[str, str]]:
    """Find projects in the given repos.

    Args:
        repos_parent: Parent directory containing all repos
        repos: List of repo names to search
        require_metadata: If True, only return projects WITH Thunderstore metadata
        exclude_with_metadata: If True, only return projects WITHOUT Thunderstore metadata

    Returns:
        List of (project_name, repo_name) tuples, sorted by project name
    """
    skip_dirs = {'bin', 'obj', 'packages', 'Releases', 'Release', 'libs', '.vs', '.git'}
    projects = []

    for repo in repos:
        ignored_projects = get_ignored_projects(repo)
        repo_path = os.path.join(repos_parent, repo)
        if not os.path.exists(repo_path):
            continue

        try:
            for item in os.listdir(repo_path):
                if item.startswith('.') or item.startswith('_') or item in skip_dirs:
                    continue

                item_path = os.path.join(repo_path, item)
                if not os.path.isdir(item_path):
                    continue

                has_csproj = False
                try:
                    for f in os.listdir(item_path):
                        if f.endswith('.csproj'):
                            has_csproj = True
                            break
                        subpath = os.path.join(item_path, f)
                        if os.path.isdir(subpath):
                            try:
                                for sf in os.listdir(subpath):
                                    if sf.endswith('.csproj'):
                                        has_csproj = True
                                        break
                            except (OSError, FileNotFoundError):
                                pass
                        if has_csproj:
                            break
                except (OSError, FileNotFoundError):
                    continue

                if not has_csproj:
                    continue

                has_metadata = _project_has_metadata(repos_parent, repo, item)

                if item in ignored_projects:
                    continue
                if require_metadata and not has_metadata:
                    continue
                if exclude_with_metadata and has_metadata:
                    continue

                projects.append((item, repo))
        except (OSError, FileNotFoundError):
            continue

    return sorted(projects, key=lambda x: x[0])


def _project_has_metadata(repos_parent: str, repo: str, project_name: str) -> bool:
    """Check if a project has Thunderstore metadata (manifest.json)."""
    repo_path = os.path.join(repos_parent, repo)

    multi_manifest = os.path.join(repo_path, 'Releases', project_name, 'manifest.json')
    if os.path.exists(multi_manifest):
        return True

    single_manifest = os.path.join(repo_path, 'Release', 'manifest.json')
    if os.path.exists(single_manifest):
        return True

    return False


def get_repos_to_search(repos_parent: str, use_all_repos: bool = False) -> tuple[Optional[list[str]], bool]:
    """Get list of repos to search for projects.

    Args:
        repos_parent: Parent directory containing all repos
        use_all_repos: If True, always use configured repos

    Returns:
        Tuple of (repos_list, is_single_repo)
    """
    if use_all_repos:
        repos = get_configured_repos()
        if not repos:
            return None, False
        return repos, False

    current_repo = detect_current_repo(repos_parent)
    if current_repo:
        return [current_repo], True

    repos = get_configured_repos()
    if repos:
        return repos, False

    return None, False
