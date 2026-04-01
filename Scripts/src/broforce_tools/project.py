"""Project discovery, identity, and path management.

This module is the single source of truth for what a project is and where it
lives. It provides the Project dataclass and all discovery/detection functions.
"""
import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .config import get_configured_repos, get_ignored_projects
from .project_types import PROJECT_TYPES, get_all_metadata_patterns


SKIP_DIRS = frozenset({'bin', 'obj', 'packages', 'Releases', 'Release', 'libs', '.vs', '.git'})


@dataclass
class Project:
    """A discovered project within a repository.

    Attributes:
        name: Project display name (e.g., "BroCeasarTrained")
        repo: Repository directory name (e.g., "BroforceOverhaulProject")
        subdir: Path from repo root to project dir. For flat projects this
            equals name. For grouped projects it's "GroupName/ProjectName".
        repos_parent: Parent directory containing all repos.
        project_type: Detected type ("mod", "bro", "wardrobe") or None.
        metadata_dir: Full path to the metadata directory (_ModContent etc.) or None.
        has_thunderstore_metadata: Whether manifest.json exists in the releases path.
    """
    name: str
    repo: str
    subdir: str
    repos_parent: str
    project_type: Optional[str] = field(default=None, compare=False, repr=False)
    metadata_dir: Optional[str] = field(default=None, compare=False, repr=False)
    has_thunderstore_metadata: bool = field(default=False, compare=False, repr=False)

    @property
    def project_dir(self) -> str:
        """Full path to the project directory."""
        return os.path.join(self.repos_parent, self.repo, self.subdir)

    @property
    def repo_dir(self) -> str:
        """Full path to the repository directory."""
        return os.path.join(self.repos_parent, self.repo)

    @property
    def source_dir(self) -> Optional[str]:
        """Parent directory of the metadata folder, or None."""
        if self.metadata_dir:
            return os.path.dirname(self.metadata_dir)
        return None

    def get_releases_path(self, create: bool = False) -> Optional[str]:
        """Get the releases path for this project.

        Delegates to the module-level get_releases_path() function.
        """
        return get_releases_path(self.repos_parent, self.repo, self.name, create=create)


# ---------------------------------------------------------------------------
# Metadata detection
# ---------------------------------------------------------------------------

def _has_mod_metadata(dir_path: str) -> bool:
    """Check if a directory contains valid project metadata."""
    patterns = get_all_metadata_patterns()
    try:
        for f in os.listdir(dir_path):
            for pattern in patterns:
                if fnmatch.fnmatch(f, pattern):
                    return True
    except (OSError, FileNotFoundError):
        pass
    return False


def find_mod_metadata_dir(project_path: str) -> Optional[str]:
    """Find the mod metadata directory within a project.

    Searches for any directory containing valid mod metadata
    (Info.json for mods, *.mod.json for bros).
    """
    skip_dirs = {'bin', 'obj', '.vs', 'packages', 'Properties'}

    for root, dirs, files in os.walk(project_path):
        depth = root[len(project_path):].count(os.sep)
        if depth > 3:
            dirs.clear()
            continue

        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for d in dirs:
            dir_path = os.path.join(root, d)
            if _has_mod_metadata(dir_path):
                return dir_path

    if _has_mod_metadata(project_path):
        return project_path

    return None


def get_source_directory(project_path: str) -> Optional[str]:
    """Get the source directory containing the mod metadata folder."""
    metadata_dir = find_mod_metadata_dir(project_path)
    if metadata_dir:
        return os.path.dirname(metadata_dir)
    return None


def detect_project_type(project_path: str) -> Optional[str]:
    """Detect project type (mod, bro, wardrobe, etc.) from metadata files."""
    metadata_dir = find_mod_metadata_dir(project_path)
    if not metadata_dir:
        return None

    try:
        for f in os.listdir(metadata_dir):
            for type_key, type_info in PROJECT_TYPES.items():
                for pattern in type_info["metadata_patterns"]:
                    if fnmatch.fnmatch(f, pattern):
                        return type_key
    except (OSError, FileNotFoundError):
        return None

    return None


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def _is_direct_project(path: str) -> bool:
    """Check if a directory is itself a project.

    A directory is a direct project if:
    - It has .csproj or metadata files at depth 0 (directly in the dir), OR
    - It has a same-named subdirectory containing .csproj/metadata (standard
      ProjectName/ProjectName/*.csproj layout), OR
    - Any immediate subdirectory contains metadata files (e.g., _ModContent/Info.json)

    .csproj files in non-matching subdirectories do NOT count — this prevents
    group folders from being falsely detected as projects when their children
    have .csproj files at their root level.
    """
    name = os.path.basename(path)
    all_patterns = get_all_metadata_patterns() + ["*.csproj"]
    metadata_only = get_all_metadata_patterns()

    # Check depth 0: files directly in the directory
    try:
        for f in os.listdir(path):
            for pattern in all_patterns:
                if fnmatch.fnmatch(f, pattern):
                    return True
    except (OSError, FileNotFoundError):
        return False

    # Check depth 1: same-named subdirectory gets the full check (csproj + metadata)
    inner = os.path.join(path, name)
    if os.path.isdir(inner):
        try:
            for f in os.listdir(inner):
                for pattern in all_patterns:
                    if fnmatch.fnmatch(f, pattern):
                        return True
        except (OSError, FileNotFoundError):
            pass

    # Check depth 1: other subdirectories only match metadata (not .csproj)
    try:
        for d in os.listdir(path):
            if d == name:
                continue
            d_path = os.path.join(path, d)
            if not os.path.isdir(d_path):
                continue
            try:
                for f in os.listdir(d_path):
                    for pattern in metadata_only:
                        if fnmatch.fnmatch(f, pattern):
                            return True
            except (OSError, FileNotFoundError):
                pass
    except (OSError, FileNotFoundError):
        pass

    return False


def _discover_in_directory(
    item: str,
    item_path: str,
    repo: str,
    repos_parent: str,
    ignored_projects: list[str],
) -> list[Project]:
    """Discover projects in a single top-level directory.

    If the directory is a direct project, returns it as a single Project.
    If it's a group folder (not a project itself, but contains project subdirs),
    returns each child project with subdir set to "group/child".
    """
    if _is_direct_project(item_path):
        if item in ignored_projects:
            return []
        project_type = detect_project_type(item_path)
        metadata_dir = find_mod_metadata_dir(item_path)
        return [Project(
            name=item,
            repo=repo,
            subdir=item,
            repos_parent=repos_parent,
            project_type=project_type,
            metadata_dir=metadata_dir,
        )]

    # Not a direct project — check for group (children that are projects)
    children = []
    try:
        for child in os.listdir(item_path):
            if child.startswith('.') or child.startswith('_') or child in SKIP_DIRS:
                continue
            child_path = os.path.join(item_path, child)
            if not os.path.isdir(child_path):
                continue
            if _is_direct_project(child_path):
                if child in ignored_projects:
                    continue
                project_type = detect_project_type(child_path)
                metadata_dir = find_mod_metadata_dir(child_path)
                children.append(Project(
                    name=child,
                    repo=repo,
                    subdir=os.path.join(item, child),
                    repos_parent=repos_parent,
                    project_type=project_type,
                    metadata_dir=metadata_dir,
                ))
    except (OSError, FileNotFoundError):
        pass

    return children


def find_projects(
    repos_parent: str,
    repos: list[str],
    require_metadata: bool = False,
    exclude_with_metadata: bool = False,
) -> list['Project']:
    """Find projects in the given repos.

    Supports both flat layouts (ProjectName directly in repo) and grouped
    layouts (GroupName/ProjectName in repo).

    Args:
        repos_parent: Parent directory containing all repos
        repos: List of repo names to search
        require_metadata: If True, only return projects WITH Thunderstore metadata
        exclude_with_metadata: If True, only return projects WITHOUT Thunderstore metadata

    Returns:
        List of Project objects, sorted by name.
    """
    projects: list[Project] = []
    seen_dirs: set[str] = set()

    for repo in repos:
        ignored_projects = get_ignored_projects(repo)
        repo_path = os.path.join(repos_parent, repo)
        if not os.path.exists(repo_path):
            continue

        project_count = count_projects_in_repo(repos_parent, repo)

        try:
            for item in os.listdir(repo_path):
                if item.startswith('.') or item.startswith('_') or item in SKIP_DIRS:
                    continue

                item_path = os.path.join(repo_path, item)
                if not os.path.isdir(item_path):
                    continue

                discovered = _discover_in_directory(
                    item, item_path, repo, repos_parent, ignored_projects,
                )

                for project in discovered:
                    real_dir = os.path.realpath(project.project_dir)
                    if real_dir in seen_dirs:
                        continue
                    seen_dirs.add(real_dir)

                    project.has_thunderstore_metadata = _project_has_metadata(
                        repos_parent, repo, project.name,
                        _project_count=project_count,
                    )
                    if require_metadata and not project.has_thunderstore_metadata:
                        continue
                    if exclude_with_metadata and project.has_thunderstore_metadata:
                        continue
                    projects.append(project)
        except (OSError, FileNotFoundError):
            continue

    return sorted(projects, key=lambda p: p.name)


def find_project_by_name(
    repos_parent: str,
    project_name: str,
    repos: Optional[list[str]] = None,
    require_metadata: bool = False,
) -> Optional['Project']:
    """Find a single project by name across configured repos.

    Replaces the duplicate search loops that existed in do_package,
    do_init_thunderstore, and the changelog commands.
    """
    if repos is None:
        repos = get_configured_repos()
        if not repos:
            repos = [
                d for d in os.listdir(repos_parent)
                if os.path.isdir(os.path.join(repos_parent, d))
            ]

    all_projects = find_projects(repos_parent, repos)
    for project in all_projects:
        if project.name == project_name:
            if require_metadata and not project.has_thunderstore_metadata:
                continue
            return project

    return None


def count_projects_in_repo(repos_parent: str, repo: str) -> int:
    """Count the number of projects in a single repo (including grouped)."""
    count = 0
    repo_path = os.path.join(repos_parent, repo)

    if not os.path.exists(repo_path):
        return 0

    try:
        for item in os.listdir(repo_path):
            if item.startswith('.') or item.startswith('_') or item in SKIP_DIRS:
                continue

            item_path = os.path.join(repo_path, item)
            if not os.path.isdir(item_path):
                continue

            if _is_direct_project(item_path):
                count += 1
            else:
                # Check for group children
                try:
                    for child in os.listdir(item_path):
                        if child.startswith('.') or child.startswith('_') or child in SKIP_DIRS:
                            continue
                        child_path = os.path.join(item_path, child)
                        if os.path.isdir(child_path) and _is_direct_project(child_path):
                            count += 1
                except (OSError, FileNotFoundError):
                    pass
    except (OSError, FileNotFoundError):
        pass

    return count


# ---------------------------------------------------------------------------
# Release path resolution
# ---------------------------------------------------------------------------

def get_releases_path(
    repos_parent: str, repo: str, project_name: str, create: bool = False,
    _project_count: Optional[int] = None,
) -> Optional[str]:
    """Get the releases path for a project.

    Single vs multi-project is determined by project count, not folder name.
    - Multi-project: <folder>/<project>/manifest.json
    - Single-project: <folder>/manifest.json

    The folder can be named Release or Releases - we use whichever exists.
    _project_count can be passed to avoid redundant directory scans.
    """
    repo_path = os.path.join(repos_parent, repo)
    releases_dir = os.path.join(repo_path, 'Releases')
    release_dir = os.path.join(repo_path, 'Release')

    project_count = _project_count if _project_count is not None else count_projects_in_repo(repos_parent, repo)
    is_multi = project_count > 1

    if not create:
        for folder in [releases_dir, release_dir]:
            if is_multi:
                path = os.path.join(folder, project_name)
            else:
                path = folder
            if os.path.exists(os.path.join(path, 'manifest.json')):
                return path
        return None

    if os.path.exists(releases_dir) and os.path.isdir(releases_dir):
        base_folder = releases_dir
    elif os.path.exists(release_dir) and os.path.isdir(release_dir):
        base_folder = release_dir
    else:
        base_folder = releases_dir if is_multi else release_dir

    if is_multi:
        return os.path.join(base_folder, project_name)
    else:
        return base_folder


def _project_has_metadata(
    repos_parent: str, repo: str, project_name: str,
    _project_count: Optional[int] = None,
) -> bool:
    """Check if a project has Thunderstore metadata (manifest.json)."""
    return get_releases_path(repos_parent, repo, project_name, create=False, _project_count=_project_count) is not None


# ---------------------------------------------------------------------------
# Repo detection
# ---------------------------------------------------------------------------

def _normalize_wsl_path(path: str) -> tuple[str, Optional[str]]:
    """Normalize a path for WSL/Windows cross-compatibility.

    Returns (primary_path, alt_path) where primary uses /mnt/X/ format
    and alt uses X:/ format (or None if not a drive path).
    """
    alt = None
    match = re.match(r'^([a-z]):/(.*)', path)
    if match:
        path = f'/mnt/{match.group(1)}/{match.group(2)}'
    else:
        match = re.match(r'^/mnt/([a-z])/(.*)', path)
        if match:
            alt = f'{match.group(1)}:/{match.group(2)}'
    return path, alt


def detect_current_repo(repos_parent: str) -> Optional[str]:
    """Detect which repo we're currently in based on cwd."""
    cwd = os.getcwd()

    cwd_original = os.path.abspath(cwd).replace('\\', '/')
    repos_original = os.path.abspath(repos_parent).replace('\\', '/')

    cwd_abs, cwd_abs_alt = _normalize_wsl_path(cwd_original.lower())
    repos_abs, repos_abs_alt = _normalize_wsl_path(repos_original.lower())

    cwd_orig_normalized, _ = _normalize_wsl_path(cwd_original.lower())
    repos_orig_normalized, _ = _normalize_wsl_path(repos_original.lower())

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


def get_repos_to_search(
    repos_parent: str, use_all_repos: bool = False
) -> tuple[Optional[list[str]], bool]:
    """Get list of repos to search for projects.

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
