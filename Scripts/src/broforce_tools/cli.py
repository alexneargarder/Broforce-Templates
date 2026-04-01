"""CLI application using Typer."""
import click.exceptions
import filecmp
import json
import os
import shutil
import time
from typing import NoReturn, Optional

import questionary
import typer

from . import __version__
from .colors import Colors, init_colors
from .paths import TemplatesDirNotFound
from .config import get_config_file, get_configured_repos, get_nix_config_file, load_config, save_config
from .paths import get_repos_parent, get_templates_dir, get_config_dir, is_windows
from .project_types import PROJECT_TYPES, get_type_names, get_display_names
from .project import (
    Project,
    detect_current_repo,
    find_project_by_name,
    find_projects,
    get_repos_to_search,
)
from .templates import (
    copyanything,
    find_replace,
    rename_files,
)
from .thunderstore import (
    CACHE_DURATION,
    add_changelog_entry,
    check_missing_required,
    clear_cache,
    do_init_thunderstore,
    do_package,
    find_changelog,
    get_cache_file,
    get_dependency_versions,
    get_latest_version_entries,
    get_unreleased_entries,
    has_unreleased_version,
)

app = typer.Typer(
    help="Tool for creating Broforce mods and packaging for Thunderstore",
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _get_repos_for_completion(repos_parent: str) -> list[str]:
    """Get repos to use for completion."""
    current_repo = detect_current_repo(repos_parent)
    if current_repo:
        return [current_repo]
    config = load_config()
    return config.get('repos', [])


def _escape_for_completion(name: str) -> str:
    """Quote project names with spaces for shell completion display."""
    if ' ' in name:
        return f'"{name}"'
    return name


def _complete_project_names_without_metadata(incomplete: str) -> list[str]:
    """Autocompletion for project names (only projects WITHOUT Thunderstore metadata)."""
    try:
        repos_parent = str(get_repos_parent())
        repos = _get_repos_for_completion(repos_parent)
        projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
        return [_escape_for_completion(p.name) for p in projects]
    except TemplatesDirNotFound:
        return []


def _complete_project_names_with_metadata(incomplete: str) -> list[str]:
    """Autocompletion for project names (only projects with Thunderstore metadata)."""
    try:
        repos_parent = str(get_repos_parent())
        repos = _get_repos_for_completion(repos_parent)
        projects = find_projects(repos_parent, repos, require_metadata=True)
        return [_escape_for_completion(p.name) for p in projects]
    except TemplatesDirNotFound:
        return []


def _complete_project_type(incomplete: str) -> list[str]:
    """Autocompletion for project type."""
    return [t for t in get_type_names() if t.startswith(incomplete.lower())]


def _complete_repos(incomplete: str) -> list[str]:
    """Autocompletion for repository names."""
    config = load_config()
    repos = config.get('repos', [])
    return [r for r in repos if r.lower().startswith(incomplete.lower())]


def _complete_none(incomplete: str) -> list[str]:
    """Return empty list to prevent file completion fallback."""
    return []


def _run_batch(projects: list[Project], action, **kwargs) -> None:
    """Run an action on multiple projects, continuing on failure."""
    failures = []
    for project in projects:
        if len(projects) > 1:
            print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
        try:
            action(project, **kwargs)
        except (SystemExit, click.exceptions.Exit):
            failures.append(project.name)
        except Exception as e:
            print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
            failures.append(project.name)
    if failures:
        print(f"\n{Colors.WARNING}{len(failures)} project(s) failed: {', '.join(failures)}{Colors.ENDC}")


def select_projects_interactive(
    repos_parent: str,
    mode: str,
    use_all_repos: bool = False,
    allow_batch: bool = True
) -> list[Project]:
    """Interactive project selection for commands."""
    repos, is_single_repo = get_repos_to_search(repos_parent, use_all_repos)
    if not repos:
        print(f"{Colors.FAIL}Error: No repos configured. Use 'bt config add-repo' to add repos.{Colors.ENDC}")
        return []

    if mode == 'package':
        projects = find_projects(repos_parent, repos, require_metadata=True)
        no_projects_msg = "No projects with Thunderstore metadata found"
        no_projects_hint = "Run: broforce-tools init-thunderstore"
        batch_label = "Package all"
    else:
        projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
        no_projects_msg = "No projects needing Thunderstore initialization found"
        no_projects_hint = "All projects already have metadata"
        batch_label = "Initialize all"

    if not projects:
        print(f"{Colors.FAIL}Error: {no_projects_msg}{Colors.ENDC}")
        print(no_projects_hint)
        return []

    if len(projects) == 1:
        print(f"{Colors.CYAN}Using project: {projects[0].name}{Colors.ENDC}")
        return [projects[0]]

    if allow_batch:
        choices = [f"{batch_label} ({len(projects)} projects)"]
    else:
        choices = []

    if is_single_repo:
        choices.extend([project.name for project in projects])
    else:
        choices.extend([f"{project.name} ({project.repo})" for project in projects])

    prompt = f"Select project:" if not is_single_repo else f"Select project from {repos[0]}:"
    selection = questionary.select(prompt, choices=choices).ask()

    if not selection:
        return []

    if allow_batch and selection.startswith(batch_label.split()[0]):
        return projects

    if is_single_repo:
        for p in projects:
            if p.name == selection:
                return [p]
        return []
    else:
        project_name = selection.rsplit(' (', 1)[0]
        for p in projects:
            if p.name == project_name:
                return [p]
        return []


def do_create_project(
    template_type: Optional[str],
    name: Optional[str],
    author: Optional[str],
    output_repo: Optional[str],
    non_interactive: bool = False,
    no_thunderstore: bool = False,
) -> None:
    """Create a new project from templates."""
    template_dir = get_templates_dir()
    repos_parent = str(get_repos_parent())
    scripts_dir = os.path.join(template_dir, 'Scripts')

    # Collect missing required values for non-interactive mode
    missing: list[tuple[str, str]] = []

    if output_repo:
        output_repo_name = output_repo
        print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")
    else:
        current_repo = detect_current_repo(repos_parent)

        if non_interactive:
            if current_repo:
                output_repo_name = current_repo
                print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")
            else:
                missing.append(("--output-repo / -o", "Target repository"))
                output_repo_name = ""
        else:
            configured_repos = get_configured_repos()

            choices = []

            if current_repo:
                choices.append(f"{current_repo} (current directory)")

            for repo in configured_repos:
                if repo != current_repo:
                    choices.append(repo)

            choices.append("Enter another repository name...")

            selection = questionary.select(
                "Select output repository:",
                choices=choices
            ).ask()

            if not selection:
                raise typer.Exit()

            if selection == "Enter another repository name...":
                output_repo_name = questionary.text(
                    "Enter repository name:"
                ).ask()
                if not output_repo_name:
                    print(f"{Colors.FAIL}Error: Repository name cannot be empty.{Colors.ENDC}")
                    raise typer.Exit(1)
            elif selection.endswith(" (current directory)"):
                output_repo_name = current_repo
            else:
                output_repo_name = selection

            print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")

    if template_type:
        pass
    elif non_interactive:
        missing.append(("--type / -t", f"Project type ({', '.join(get_type_names())})"))
    else:
        choice = questionary.select(
            "What would you like to create?",
            choices=get_display_names()
        ).ask()

        if not choice:
            raise typer.Exit()

        template_type = choice.lower()

    type_info = PROJECT_TYPES.get(template_type) if template_type else None
    if template_type and not type_info:
        print(f"{Colors.FAIL}Error: Invalid project type '{template_type}'{Colors.ENDC}")
        print(f"Valid types: {', '.join(get_type_names())}")
        raise typer.Exit(1)
    if type_info:
        source_template_name = type_info["template_dir_name"]
    else:
        source_template_name = ""

    if name:
        newName = name
    elif non_interactive:
        missing.append(("--name / -n", "Project name"))
        newName = ""
    else:
        newName = questionary.text(f"Enter {template_type} name:").ask()
        if not newName:
            print(f"{Colors.FAIL}Error: Name cannot be empty.{Colors.ENDC}")
            raise typer.Exit(1)

    newNameWithUnderscore = newName.replace(' ', '_')
    newNameNoSpaces = newName.replace(' ', '')

    if author:
        authorName = author
    elif non_interactive:
        missing.append(("--author / -a", "Author name"))
        authorName = ""
    else:
        authorName = questionary.text("Enter author name (e.g., YourName):").ask()
        if not authorName:
            print(f"{Colors.FAIL}Error: Author name cannot be empty.{Colors.ENDC}")
            raise typer.Exit(1)

    # Check for missing required values in non-interactive mode
    check_missing_required(missing)

    templatePath = os.path.join(template_dir, source_template_name)
    output_repo_path = os.path.join(repos_parent, output_repo_name)

    if not os.path.exists(output_repo_path):
        print(f"{Colors.FAIL}Error: Output repository does not exist: {output_repo_path}{Colors.ENDC}")
        print(f"{Colors.WARNING}Please ensure the repository '{output_repo_name}' exists in: {repos_parent}{Colors.ENDC}")
        raise typer.Exit(1)

    if type_info and type_info["has_code"] and output_repo_path != template_dir:
        output_scripts_dir = os.path.join(output_repo_path, 'Scripts')
        if not os.path.exists(output_scripts_dir):
            os.makedirs(output_scripts_dir)
            print(f"{Colors.GREEN}Created Scripts directory: {output_scripts_dir}{Colors.ENDC}")

        targets_source = os.path.join(scripts_dir, 'BroforceModBuild.targets')
        targets_dest = os.path.join(output_scripts_dir, 'BroforceModBuild.targets')

        if os.path.exists(targets_source):
            try:
                if not os.path.exists(targets_dest):
                    shutil.copy2(targets_source, targets_dest)
                    print(f"{Colors.GREEN}Copied BroforceModBuild.targets to output repository{Colors.ENDC}")
                else:
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

    releases_dir = os.path.join(output_repo_path, 'Releases')
    release_dir = os.path.join(output_repo_path, 'Release')
    if os.path.isdir(release_dir) and not os.path.isdir(releases_dir):
        base_release = release_dir
    else:
        base_release = releases_dir
    newReleaseFolder = os.path.join(base_release, newName)
    newRepoPath = os.path.join(output_repo_path, newName)

    if not os.path.exists(templatePath):
        print(f"{Colors.FAIL}Error: Template directory not found: {templatePath}{Colors.ENDC}")
        print(f"Please ensure the '{source_template_name}' directory exists in your repository.")
        raise typer.Exit(1)

    if os.path.exists(newReleaseFolder):
        print(f"{Colors.FAIL}Error: Release directory already exists: {newReleaseFolder}{Colors.ENDC}")
        print(f"Please choose a different {template_type} name or remove the existing directory.")
        raise typer.Exit(1)

    if os.path.exists(newRepoPath):
        print(f"{Colors.FAIL}Error: Repository directory already exists: {newRepoPath}{Colors.ENDC}")
        print(f"Please choose a different {template_type} name or remove the existing directory.")
        raise typer.Exit(1)

    try:
        os.makedirs(newReleaseFolder, exist_ok=True)
        copyanything(templatePath, newRepoPath)
    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed to copy template files: {e}{Colors.ENDC}")
        if os.path.exists(newReleaseFolder):
            shutil.rmtree(newReleaseFolder)
        if os.path.exists(newRepoPath):
            shutil.rmtree(newRepoPath)
        raise typer.Exit(1)

    try:
        rename_files(newRepoPath, source_template_name, newName)
        rename_files(newRepoPath, type_info["class_prefix"], newNameNoSpaces)

        fileTypes = type_info["file_patterns"]

        for fileType in fileTypes:
            find_replace(newRepoPath, source_template_name, newName, fileType)
            find_replace(newRepoPath, source_template_name.replace(' ', '_'), newNameWithUnderscore, fileType)
            find_replace(newRepoPath, type_info["class_prefix"], newNameNoSpaces, fileType)

            find_replace(newRepoPath, "AUTHOR_NAME", authorName, fileType)
            find_replace(newRepoPath, "REPO_NAME", output_repo_name, fileType)

        if template_type == "bro":
            find_replace(newRepoPath, "BroTemplate.cs", f"{newNameNoSpaces}.cs", "*.csproj")

            dep_versions = get_dependency_versions()
            bromaker_version = dep_versions.get('BroMaker', '2.6.0')

            find_replace(newRepoPath, "BROMAKER_VERSION", bromaker_version, "*.json")

        changelogPath = os.path.join(newReleaseFolder, 'Changelog.md')
        changelogContent = '''## v1.0.0 (unreleased)
- Initial release
'''

        with open(changelogPath, 'w', encoding='utf-8') as changelogFile:
            changelogFile.write(changelogContent)

        print(f"\n{Colors.GREEN}{Colors.BOLD}Success! Created new {template_type} '{newName}'{Colors.ENDC}")
        if output_repo:
            print(f"{Colors.CYAN}Output repository:{Colors.ENDC} {output_repo_name}")
        print(f"{Colors.CYAN}Source files:{Colors.ENDC} {newRepoPath}")
        print(f"{Colors.CYAN}Releases folder:{Colors.ENDC} {newReleaseFolder}")

        if no_thunderstore:
            print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
            if type_info["has_code"]:
                print(f"  1. Open the project in Visual Studio")
                print(f"  2. Build the project (builds to game automatically)")
                print(f"  3. Launch Broforce to test your {template_type}")
                print(f"  4. Run 'bt init-thunderstore' when ready to publish")
            else:
                print(f"  1. Edit the .fa.json file to set the Wearer and sprite")
                print(f"  2. Replace placeholder.png with your sprite")
                print(f"  3. Run 'bt init-thunderstore' when ready to publish")
        elif non_interactive:
            print(f"\n{Colors.CYAN}Note: Run 'bt init-thunderstore' to set up Thunderstore metadata.{Colors.ENDC}")
        else:
            setup_thunderstore = questionary.confirm(
                "Set up Thunderstore metadata now?",
                default=True
            ).ask()

            if setup_thunderstore is None:
                raise typer.Exit()
            elif setup_thunderstore:
                print()
                new_project = Project(
                    name=newName,
                    repo=output_repo_name,
                    subdir=newName,
                    repos_parent=repos_parent,
                    project_type=template_type,
                )
                do_init_thunderstore(new_project)
            else:
                print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
                if type_info["has_code"]:
                    print(f"  1. Open the project in Visual Studio")
                    print(f"  2. Build the project (builds to game automatically)")
                    print(f"  3. Launch Broforce to test your {template_type}")
                    print(f"  4. Run 'bt init-thunderstore' when ready to publish")
                else:
                    print(f"  1. Edit the .fa.json file to set the Wearer and sprite")
                    print(f"  2. Replace placeholder.png with your sprite")
                    print(f"  3. Run 'bt init-thunderstore' when ready to publish")

    except (SystemExit, click.exceptions.Exit):
        raise
    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed during file processing: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        if os.path.exists(newReleaseFolder):
            shutil.rmtree(newReleaseFolder)
        if os.path.exists(newRepoPath):
            shutil.rmtree(newRepoPath)
        raise typer.Exit(1)


def _select_project_for_changelog(repos_parent: str) -> Optional[tuple[Project, str, str]]:
    """Interactive project selection for changelog commands.

    Returns (project, releases_path, changelog_path) or None if cancelled.
    """
    repos, _ = get_repos_to_search(repos_parent, use_all_repos=False)
    if not repos:
        print(f"{Colors.FAIL}Error: No repos configured. Use 'bt config add-repo' to add repos.{Colors.ENDC}")
        return None

    projects = find_projects(repos_parent, repos, require_metadata=True)
    if not projects:
        print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
        return None

    if len(projects) == 1:
        project = projects[0]
        print(f"{Colors.CYAN}Using project: {project.name}{Colors.ENDC}")
    else:
        choices = [f"{project.name} ({project.repo})" for project in projects]
        selection = questionary.select("Select project:", choices=choices).ask()
        if not selection:
            return None
        selected_name = selection.rsplit(' (', 1)[0]
        project = None
        for p in projects:
            if p.name == selected_name:
                project = p
                break
        if not project:
            return None

    releases_path = project.get_releases_path(create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project.name}'{Colors.ENDC}")
        return None

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project.name}'{Colors.ENDC}")
        return None

    return project, releases_path, changelog_path


def _interactive_changelog_show(repos_parent: str) -> None:
    """Show changelog entries via interactive project selection."""
    result = _select_project_for_changelog(repos_parent)
    if not result:
        raise typer.Exit()

    project, _, changelog_path = result
    version, is_unreleased, entries = get_latest_version_entries(changelog_path)
    if not version:
        print(f"{Colors.CYAN}{project.name}: No versions found in changelog{Colors.ENDC}")
        raise typer.Exit()

    status = "(unreleased)" if is_unreleased else "(released)"
    print(f"{Colors.HEADER}{project.name} - v{version} {status}:{Colors.ENDC}")
    if entries:
        for entry in entries:
            print(f"  {entry}")
    else:
        print(f"  {Colors.CYAN}(no entries){Colors.ENDC}")


def _interactive_changelog_add(repos_parent: str) -> None:
    """Add a changelog entry via interactive prompts."""
    message = questionary.text("Enter changelog entry:").ask()
    if not message:
        raise typer.Exit()

    result = _select_project_for_changelog(repos_parent)
    if not result:
        raise typer.Exit()

    project, _, changelog_path = result

    is_unreleased, version = has_unreleased_version(changelog_path)
    if not is_unreleased:
        print(f"{Colors.FAIL}Error: No unreleased version found in changelog{Colors.ENDC}")
        print(f"Add a version header like: ## v1.0.0 (unreleased)")
        raise typer.Exit(1)

    if add_changelog_entry(changelog_path, message):
        print(f"{Colors.GREEN}Added to {project.name} v{version}:{Colors.ENDC}")
        print(f"  - {message}")
    else:
        print(f"{Colors.FAIL}Error: Failed to add changelog entry{Colors.ENDC}")
        raise typer.Exit(1)


def _interactive_changelog_edit(repos_parent: str) -> None:
    """Open a changelog in an editor via interactive project selection."""
    import shlex
    import subprocess

    result = _select_project_for_changelog(repos_parent)
    if not result:
        raise typer.Exit()

    _, _, changelog_path = result

    fallback = 'notepad' if is_windows() else 'nano'
    editor = os.environ.get('EDITOR', os.environ.get('VISUAL', fallback))
    print(f"{Colors.CYAN}Opening {changelog_path} in {editor}...{Colors.ENDC}")

    try:
        editor_cmd = shlex.split(editor) + [changelog_path]
        subprocess.run(editor_cmd, check=True)
    except FileNotFoundError:
        print(f"{Colors.FAIL}Error: Editor '{editor.split()[0]}' not found{Colors.ENDC}")
        print(f"Set the EDITOR environment variable to your preferred editor")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        print(f"{Colors.FAIL}Error: Editor exited with code {e.returncode}{Colors.ENDC}")
        raise typer.Exit(1)


def _version_callback(value: bool):
    if value:
        print(f"broforce-tools {__version__}")
        raise typer.Exit()


def _handle_templates_not_found() -> NoReturn:
    """Print helpful error when Broforce-Templates directory cannot be found."""
    print(f"{Colors.FAIL}Error: Could not find Broforce-Templates directory.{Colors.ENDC}")
    print(f"\n{Colors.CYAN}To configure:{Colors.ENDC}")
    print(f"  bt config init                         Interactive setup")
    print(f"  bt config set repos_parent <path>      Set repos directory")
    print(f"  BROFORCE_TEMPLATES_DIR=<path> bt ...    Environment variable")
    raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True, help="Show version"),
    clear_cache_flag: bool = typer.Option(False, "--clear-cache", help="Clear dependency version cache"),
):
    """Tool for creating Broforce mods and packaging for Thunderstore."""
    init_colors()

    if clear_cache_flag:
        cache_file = get_cache_file()
        if cache_file.exists():
            if clear_cache():
                print(f"{Colors.GREEN}Dependency cache cleared: {cache_file}{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}Error clearing cache{Colors.ENDC}")
                raise typer.Exit(1)
        else:
            print(f"{Colors.BLUE}Cache file does not exist: {cache_file}{Colors.ENDC}")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

    # Interactive menu - needs repos_parent
    try:
        repos_parent = str(get_repos_parent())
    except TemplatesDirNotFound:
        _handle_templates_not_found()

    print(f"{Colors.HEADER}Broforce Mod Tools{Colors.ENDC}\n")

    choice = questionary.select(
        "What would you like to do?",
        choices=[
            f"Create new {' / '.join(get_type_names())} project",
            "Setup Thunderstore metadata for an existing project",
            "Package for releasing on Thunderstore",
            "View/package unreleased projects",
            "Manage changelogs",
            "Manage configuration",
            "Show dependency versions",
            "Show help"
        ]
    ).ask()

    if not choice:
        raise typer.Exit()

    if choice == "Show help":
        print(ctx.get_help())
        raise typer.Exit()
    elif choice.startswith("Create new"):
        do_create_project(None, None, None, None)
    elif choice == "Setup Thunderstore metadata for an existing project":
        selected = select_projects_interactive(repos_parent, 'init', use_all_repos=False)
        if not selected:
            raise typer.Exit()
        _run_batch(selected, do_init_thunderstore)
    elif choice == "Package for releasing on Thunderstore":
        selected = select_projects_interactive(repos_parent, 'package', use_all_repos=False)
        if not selected:
            raise typer.Exit()
        _run_batch(selected, do_package)
    elif choice == "View/package unreleased projects":
        unreleased(all_repos=False, non_interactive=False, package_all=False, package=None)
    elif choice == "Manage changelogs":
        sub = questionary.select(
            "Changelog action:",
            choices=["Add entry", "Show entries", "Edit in editor"]
        ).ask()
        if not sub:
            raise typer.Exit()
        if sub == "Add entry":
            _interactive_changelog_add(repos_parent)
        elif sub == "Show entries":
            _interactive_changelog_show(repos_parent)
        elif sub == "Edit in editor":
            _interactive_changelog_edit(repos_parent)
    elif choice == "Manage configuration":
        _interactive_config(repos_parent)
    elif choice == "Show dependency versions":
        deps(refresh=False)


@app.command()
def create(
    type: Optional[str] = typer.Option(None, "-t", "--type", help=f"Project type: {', '.join(get_type_names())}", autocompletion=_complete_project_type),
    name: Optional[str] = typer.Option(None, "-n", "--name", help="Project name", autocompletion=_complete_none),
    author: Optional[str] = typer.Option(None, "-a", "--author", help="Author name", autocompletion=_complete_none),
    output_repo: Optional[str] = typer.Option(None, "-o", "--output-repo", help="Target repository", autocompletion=_complete_repos),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
    no_thunderstore: bool = typer.Option(False, "--no-thunderstore", help="Skip Thunderstore metadata setup"),
):
    """Create a new project from templates."""
    init_colors()
    do_create_project(type, name, author, output_repo, non_interactive, no_thunderstore)


@app.command("init-thunderstore")
def init_thunderstore_cmd(
    project_name: Optional[str] = typer.Argument(None, help="Project name (optional)", autocompletion=_complete_project_names_without_metadata),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
    namespace: Optional[str] = typer.Option(None, "-n", "--namespace", help="Thunderstore namespace/author", autocompletion=_complete_none),
    description: Optional[str] = typer.Option(None, "-d", "--description", help="Package description (max 250 chars)", autocompletion=_complete_none),
    website_url: Optional[str] = typer.Option(None, "-w", "--website-url", help="Website/GitHub URL", autocompletion=_complete_none),
    package_name: Optional[str] = typer.Option(None, "-p", "--package-name", help="Override package name", autocompletion=_complete_none),
):
    """Initialize Thunderstore metadata for an existing project."""
    init_colors()
    repos_parent = str(get_repos_parent())

    # In non-interactive mode, project_name is required
    if non_interactive and not project_name:
        print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
        raise typer.Exit(1)

    if project_name:
        project = find_project_by_name(repos_parent, project_name)
        if not project:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)
        do_init_thunderstore(
            project,
            namespace=namespace,
            description=description,
            website_url=website_url,
            package_name_override=package_name,
            non_interactive=non_interactive,
        )
    else:
        selected = select_projects_interactive(repos_parent, 'init', use_all_repos=all_repos)
        if not selected:
            raise typer.Exit()
        _run_batch(
            selected, do_init_thunderstore,
            namespace=namespace,
            description=description,
            website_url=website_url,
            package_name_override=package_name,
            non_interactive=non_interactive,
        )


@app.command()
def package(
    project_name: Optional[str] = typer.Argument(None, help="Project name (optional)", autocompletion=_complete_project_names_with_metadata),
    version: Optional[str] = typer.Option(None, "--version", help="Override version", autocompletion=_complete_none),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
    allow_outdated_changelog: bool = typer.Option(False, "--allow-outdated-changelog", help="Package even if changelog version is behind"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing package ZIP"),
    update_deps: Optional[bool] = typer.Option(None, "--update-deps/--no-update-deps", help="Update outdated dependencies (default: yes in non-interactive)"),
    add_missing_deps: Optional[bool] = typer.Option(None, "--add-missing-deps/--no-add-missing-deps", help="Add missing dependencies (default: yes in non-interactive)"),
    keep_unreleased: bool = typer.Option(False, "--keep-unreleased", help="Don't strip '(unreleased)' tag from source changelog (for test packaging)"),
):
    """Create a Thunderstore-ready ZIP package."""
    init_colors()
    repos_parent = str(get_repos_parent())

    # In non-interactive mode, project_name is required
    if non_interactive and not project_name:
        print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
        raise typer.Exit(1)

    if project_name:
        project = find_project_by_name(repos_parent, project_name, require_metadata=True)
        if not project:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)
        do_package(
            project, version,
            non_interactive=non_interactive,
            allow_outdated_changelog=allow_outdated_changelog,
            overwrite=overwrite,
            update_deps=update_deps,
            add_missing_deps=add_missing_deps,
            keep_unreleased=keep_unreleased,
        )
    else:
        selected = select_projects_interactive(repos_parent, 'package', use_all_repos=all_repos)
        if not selected:
            raise typer.Exit()
        _run_batch(
            selected, do_package,
            version_override=version,
            non_interactive=non_interactive,
            allow_outdated_changelog=allow_outdated_changelog,
            overwrite=overwrite,
            update_deps=update_deps,
            add_missing_deps=add_missing_deps,
            keep_unreleased=keep_unreleased,
        )


@app.command()
def unreleased(
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
    package_all: bool = typer.Option(False, "--package-all", help="Package all unreleased projects"),
    package: Optional[list[str]] = typer.Option(None, "--package", help="Package specific project(s)"),
):
    """List projects with unreleased changes and optionally package them."""
    init_colors()
    repos_parent = str(get_repos_parent())

    repos, is_single_repo = get_repos_to_search(repos_parent, all_repos)
    if not repos:
        print(f"{Colors.FAIL}Error: No repos configured. Use 'bt config add-repo' to add repos.{Colors.ENDC}")
        raise typer.Exit(1)

    projects = find_projects(repos_parent, repos, require_metadata=True)
    if not projects:
        print(f"{Colors.CYAN}No projects with Thunderstore metadata found.{Colors.ENDC}")
        raise typer.Exit()

    unreleased_by_repo: dict[str, list[tuple[Project, str, list[str]]]] = {}

    for project in projects:
        releases_path = project.get_releases_path(create=False)
        if not releases_path:
            continue

        changelog_path = find_changelog(releases_path)
        if not changelog_path:
            continue

        is_unreleased, version = has_unreleased_version(changelog_path)
        if is_unreleased:
            _, entries = get_unreleased_entries(changelog_path)
            if project.repo not in unreleased_by_repo:
                unreleased_by_repo[project.repo] = []
            unreleased_by_repo[project.repo].append((project, version, entries))

    if not unreleased_by_repo:
        print(f"{Colors.CYAN}No projects with unreleased changes found.{Colors.ENDC}")
        raise typer.Exit()

    def print_unreleased_list(show_details: bool):
        print(f"{Colors.HEADER}Projects with unreleased changes:{Colors.ENDC}\n")
        all_projects: list[Project] = []
        for repo_name in sorted(unreleased_by_repo.keys()):
            print(f"{Colors.BLUE}{repo_name}:{Colors.ENDC}")
            for project, version, entries in sorted(unreleased_by_repo[repo_name], key=lambda x: x[0].name):
                print(f"  {project.name} (v{version})")
                all_projects.append(project)
                if show_details and entries:
                    for entry in entries:
                        print(f"    {Colors.CYAN}{entry}{Colors.ENDC}")
            print()
        return all_projects

    all_unreleased: list[Project] = []
    for repo_name in sorted(unreleased_by_repo.keys()):
        for project, version, entries in sorted(unreleased_by_repo[repo_name], key=lambda x: x[0].name):
            all_unreleased.append(project)

    # Handle non-interactive mode
    if non_interactive or package_all or package:
        print_unreleased_list(False)

        if package_all:
            _run_batch(all_unreleased, do_package, non_interactive=True)
        elif package:
            project_names = {p.name for p in all_unreleased}
            to_package: list[Project] = []
            for proj in package:
                if proj not in project_names:
                    print(f"{Colors.WARNING}Warning: '{proj}' not found in unreleased projects, skipping{Colors.ENDC}")
                    continue
                for p in all_unreleased:
                    if p.name == proj:
                        to_package.append(p)
                        break
            if to_package:
                _run_batch(to_package, do_package, non_interactive=True)
        return

    # Interactive mode
    show_details = False
    all_unreleased = print_unreleased_list(show_details)
    total_count = len(all_unreleased)

    while True:
        toggle_label = "Hide details" if show_details else "Show details"
        choices = [
            "Package selected projects",
            f"Package all ({total_count} projects)",
            toggle_label,
            "Exit"
        ]

        selection = questionary.select("What would you like to do?", choices=choices).ask()

        if not selection or selection == "Exit":
            raise typer.Exit()

        if selection in ("Show details", "Hide details"):
            show_details = not show_details
            print()
            all_unreleased = print_unreleased_list(show_details)
            continue

        break

    if selection.startswith("Package all"):
        _run_batch(all_unreleased, do_package)
    else:
        if is_single_repo:
            project_choices = [p.name for p in all_unreleased]
        else:
            project_choices = [f"{p.name} ({p.repo})" for p in all_unreleased]

        selected = questionary.checkbox(
            "Select projects to package:",
            choices=project_choices
        ).ask()

        if not selected:
            print(f"{Colors.CYAN}No projects selected.{Colors.ENDC}")
            raise typer.Exit()

        to_package: list[Project] = []
        for sel in selected:
            if is_single_repo:
                for p in all_unreleased:
                    if p.name == sel:
                        to_package.append(p)
                        break
            else:
                proj_name = sel.rsplit(' (', 1)[0]
                for p in all_unreleased:
                    if p.name == proj_name:
                        to_package.append(p)
                        break

        _run_batch(to_package, do_package)


@app.command()
def deps(
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Force re-fetch from Thunderstore API"),
):
    """Show dependency versions (cached from Thunderstore API)."""
    init_colors()
    cache_file = get_cache_file()

    if refresh:
        clear_cache()
        print(f"{Colors.CYAN}Fetching latest versions from Thunderstore...{Colors.ENDC}")
        versions = get_dependency_versions()
        print(f"{Colors.GREEN}Cache refreshed.{Colors.ENDC}\n")
    else:
        versions = get_dependency_versions()

    fallbacks = set()
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            fallbacks = set(cache_data.get('fallbacks', []))
        except (json.JSONDecodeError, OSError):
            pass

    print(f"{Colors.HEADER}Dependency versions:{Colors.ENDC}")
    for name, version in sorted(versions.items()):
        if name in fallbacks:
            print(f"  {name}: {version} {Colors.WARNING}(fallback - API unreachable){Colors.ENDC}")
        else:
            print(f"  {name}: {version}")

    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            cache_time = cache_data.get('timestamp', 0)
            age_seconds = time.time() - cache_time
            if age_seconds < 60:
                age_str = f"{int(age_seconds)}s"
            elif age_seconds < 3600:
                age_str = f"{int(age_seconds / 60)}m"
            else:
                age_str = f"{age_seconds / 3600:.1f}h"
            expires_in = CACHE_DURATION - age_seconds
            if expires_in > 0:
                if expires_in < 3600:
                    exp_str = f"{int(expires_in / 60)}m"
                else:
                    exp_str = f"{expires_in / 3600:.1f}h"
                print(f"\n{Colors.CYAN}Cache age: {age_str} (expires in {exp_str}){Colors.ENDC}")
            else:
                print(f"\n{Colors.WARNING}Cache expired (age: {age_str}){Colors.ENDC}")
        except (json.JSONDecodeError, OSError):
            pass
    print(f"{Colors.CYAN}Use --refresh to force re-fetch from Thunderstore API{Colors.ENDC}")


changelog_app = typer.Typer(help="Manage project changelogs")
app.add_typer(changelog_app, name="changelog")


@changelog_app.command("add")
def changelog_add(
    arg1: Optional[str] = typer.Argument(
        None,
        help="Project name (if 2 args) or message (if 1 arg)",
        autocompletion=_complete_project_names_with_metadata
    ),
    arg2: Optional[str] = typer.Argument(None, help="Message (if 2 args)"),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
):
    """Add an entry to a project's unreleased changelog section."""
    init_colors()
    repos_parent = str(get_repos_parent())

    if not isinstance(arg1, str):
        arg1 = None
    if not isinstance(arg2, str):
        arg2 = None
    if not isinstance(non_interactive, bool):
        non_interactive = False

    # Handle missing arguments
    if arg1 is None:
        if non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires project and message arguments.{Colors.ENDC}")
            print(f"Usage: bt changelog add -y \"ProjectName\" \"Message\"")
            raise typer.Exit(1)
        else:
            print(f"{Colors.FAIL}Error: Message argument required.{Colors.ENDC}")
            print(f"Usage: bt changelog add \"Message\"")
            print(f"       bt changelog add \"ProjectName\" \"Message\"")
            raise typer.Exit(1)

    if arg2 is None:
        message = arg1
        repos, _ = get_repos_to_search(repos_parent, all_repos)
        if not repos:
            print(f"{Colors.FAIL}Error: No repos configured. Use 'bt config add-repo' to add repos.{Colors.ENDC}")
            raise typer.Exit(1)

        projects = find_projects(repos_parent, repos, require_metadata=True)
        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
            raise typer.Exit(1)

        if len(projects) == 1:
            project = projects[0]
            print(f"{Colors.CYAN}Using project: {project.name}{Colors.ENDC}")
        elif non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires specifying project name.{Colors.ENDC}")
            print(f"Usage: bt changelog add \"ProjectName\" \"Message\"")
            print(f"\nAvailable projects:")
            for p in projects:
                print(f"  - {p.name}")
            raise typer.Exit(1)
        else:
            choices = [f"{p.name} ({p.repo})" for p in projects]
            selection = questionary.select("Select project:", choices=choices).ask()
            if not selection:
                raise typer.Exit()
            selected_name = selection.rsplit(' (', 1)[0]
            project = None
            for p in projects:
                if p.name == selected_name:
                    project = p
                    break
            if not project:
                print(f"{Colors.FAIL}Error: Could not find project '{selected_name}'{Colors.ENDC}")
                raise typer.Exit(1)
    else:
        project_name = arg1
        message = arg2
        project = find_project_by_name(repos_parent, project_name)
        if not project:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)

    releases_path = project.get_releases_path(create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project.name}'{Colors.ENDC}")
        raise typer.Exit(1)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project.name}'{Colors.ENDC}")
        raise typer.Exit(1)

    is_unreleased, version = has_unreleased_version(changelog_path)
    if not is_unreleased:
        print(f"{Colors.FAIL}Error: No unreleased version found in changelog{Colors.ENDC}")
        print(f"Add a version header like: ## v1.0.0 (unreleased)")
        raise typer.Exit(1)

    if add_changelog_entry(changelog_path, message):
        print(f"{Colors.GREEN}Added to {project.name} v{version}:{Colors.ENDC}")
        print(f"  - {message}")
    else:
        print(f"{Colors.FAIL}Error: Failed to add changelog entry{Colors.ENDC}")
        raise typer.Exit(1)


@changelog_app.command("edit")
def changelog_edit(
    project_name: Optional[str] = typer.Argument(
        None,
        help="Project name",
        autocompletion=_complete_project_names_with_metadata
    ),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
):
    """Open a project's changelog in an editor."""
    init_colors()
    repos_parent = str(get_repos_parent())

    if not isinstance(project_name, str):
        project_name = None

    if project_name:
        project = find_project_by_name(repos_parent, project_name)
        if not project:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)
    else:
        repos, _ = get_repos_to_search(repos_parent, all_repos)
        if not repos:
            print(f"{Colors.FAIL}Error: No repos configured. Use 'bt config add-repo' to add repos.{Colors.ENDC}")
            raise typer.Exit(1)

        projects = find_projects(repos_parent, repos, require_metadata=True)
        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
            raise typer.Exit(1)

        if len(projects) == 1:
            project = projects[0]
            print(f"{Colors.CYAN}Using project: {project.name}{Colors.ENDC}")
        elif non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
            print(f"\nAvailable projects:")
            for p in projects:
                print(f"  - {p.name}")
            raise typer.Exit(1)
        else:
            choices = [f"{p.name} ({p.repo})" for p in projects]
            selection = questionary.select("Select project:", choices=choices).ask()
            if not selection:
                raise typer.Exit()
            selected_name = selection.rsplit(' (', 1)[0]
            project = None
            for p in projects:
                if p.name == selected_name:
                    project = p
                    break
            if not project:
                print(f"{Colors.FAIL}Error: Could not find project '{selected_name}'{Colors.ENDC}")
                raise typer.Exit(1)

    releases_path = project.get_releases_path(create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project.name}'{Colors.ENDC}")
        raise typer.Exit(1)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project.name}'{Colors.ENDC}")
        raise typer.Exit(1)

    fallback = 'notepad' if is_windows() else 'nano'
    editor = os.environ.get('EDITOR', os.environ.get('VISUAL', fallback))
    print(f"{Colors.CYAN}Opening {changelog_path} in {editor}...{Colors.ENDC}")

    import shlex
    import subprocess
    try:
        editor_cmd = shlex.split(editor) + [changelog_path]
        subprocess.run(editor_cmd, check=True)
    except FileNotFoundError:
        print(f"{Colors.FAIL}Error: Editor '{editor.split()[0]}' not found{Colors.ENDC}")
        print(f"Set the EDITOR environment variable to your preferred editor")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        print(f"{Colors.FAIL}Error: Editor exited with code {e.returncode}{Colors.ENDC}")
        raise typer.Exit(1)


@changelog_app.command("show")
def changelog_show(
    project_name: Optional[str] = typer.Argument(
        None,
        help="Project name",
        autocompletion=_complete_project_names_with_metadata
    ),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
):
    """Show the latest changelog entries for a project."""
    init_colors()
    repos_parent = str(get_repos_parent())

    if not isinstance(project_name, str):
        project_name = None

    if project_name:
        project = find_project_by_name(repos_parent, project_name)
        if not project:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)
    else:
        repos, _ = get_repos_to_search(repos_parent, all_repos)
        if not repos:
            print(f"{Colors.FAIL}Error: No repos configured. Use 'bt config add-repo' to add repos.{Colors.ENDC}")
            raise typer.Exit(1)

        projects = find_projects(repos_parent, repos, require_metadata=True)
        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
            raise typer.Exit(1)

        if len(projects) == 1:
            project = projects[0]
            print(f"{Colors.CYAN}Using project: {project.name}{Colors.ENDC}")
        elif non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
            print(f"\nAvailable projects:")
            for p in projects:
                print(f"  - {p.name}")
            raise typer.Exit(1)
        else:
            choices = []
            project_map: dict[str, Project] = {}
            unreleased_set = set()
            for p in projects:
                rel_path = p.get_releases_path(create=False)
                is_unreleased = False
                if rel_path:
                    cl_path = find_changelog(rel_path)
                    if cl_path:
                        is_unreleased, _ = has_unreleased_version(cl_path)
                if is_unreleased:
                    display = f"{p.name} ({p.repo}) *"
                    unreleased_set.add(display)
                else:
                    display = f"{p.name} ({p.repo})"
                choices.append(display)
                project_map[display] = p

            choices.sort(key=lambda x: (x not in unreleased_set, x))

            selection = questionary.select("Select project (* = unreleased):", choices=choices).ask()
            if not selection:
                raise typer.Exit()
            project = project_map[selection]

    releases_path = project.get_releases_path(create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project.name}'{Colors.ENDC}")
        raise typer.Exit(1)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project.name}'{Colors.ENDC}")
        raise typer.Exit(1)

    version, is_unreleased, entries = get_latest_version_entries(changelog_path)
    if not version:
        print(f"{Colors.CYAN}{project.name}: No versions found in changelog{Colors.ENDC}")
        raise typer.Exit()

    status = "(unreleased)" if is_unreleased else "(released)"
    print(f"{Colors.HEADER}{project.name} - v{version} {status}:{Colors.ENDC}")
    if entries:
        for entry in entries:
            print(f"  {entry}")
    else:
        print(f"  {Colors.CYAN}(no entries){Colors.ENDC}")


# =============================================================================
# Config commands
# =============================================================================

config_app = typer.Typer(help="Manage broforce-tools configuration", invoke_without_command=True)
app.add_typer(config_app, name="config")


@config_app.callback()
def config_callback(ctx: typer.Context):
    """Manage broforce-tools configuration."""
    if ctx.invoked_subcommand is not None:
        return
    init_colors()
    try:
        repos_parent = str(get_repos_parent())
    except TemplatesDirNotFound:
        repos_parent = None
    _interactive_config(repos_parent)
    raise typer.Exit()


CONFIG_SETTABLE_KEYS = {
    'repos_parent': 'Parent directory containing all repos',
    'release_dir': 'Central directory for release zip copies',
    'templates_dir': 'Path to Broforce-Templates directory',
    'defaults.namespace': 'Default Thunderstore namespace/author',
    'defaults.website_url': 'Default website URL for Thunderstore packages',
}


@config_app.command("show")
def config_show():
    """Print current config file path and contents."""
    init_colors()
    nix_file = get_nix_config_file()
    user_file = get_config_file()
    has_nix = nix_file.exists()
    has_user = user_file.exists()

    if has_nix:
        print(f"{Colors.CYAN}Nix config:{Colors.ENDC}  {nix_file}")
    if has_user:
        print(f"{Colors.CYAN}User config:{Colors.ENDC} {user_file}")
    elif not has_nix:
        print(f"{Colors.CYAN}Config file:{Colors.ENDC} {user_file}")
        print(f"{Colors.WARNING}Config file does not exist yet.{Colors.ENDC}")
        print(f"Run {Colors.CYAN}bt config init{Colors.ENDC} to get started.")
        return

    if has_nix and has_user:
        print(f"\n{Colors.CYAN}Merged config (user overrides nix):{Colors.ENDC}")
    elif has_nix:
        print(f"\n{Colors.CYAN}Config (from nix):{Colors.ENDC}")

    config = load_config()
    print(json.dumps(config, indent=2))


@config_app.command("path")
def config_path():
    """Print the config file path."""
    print(str(get_config_file()))


@config_app.command("edit")
def config_edit():
    """Open config file in $EDITOR."""
    init_colors()
    import shlex
    import subprocess
    config_file = get_config_file()
    if not config_file.exists():
        from .paths import ensure_dir
        ensure_dir(config_file.parent)
        config_file.write_text('{\n  "repos": []\n}\n')
        print(f"{Colors.GREEN}Created config file: {config_file}{Colors.ENDC}")

    fallback = 'notepad' if is_windows() else 'nano'
    editor = os.environ.get('EDITOR', os.environ.get('VISUAL', fallback))
    print(f"{Colors.CYAN}Opening {config_file} in {editor}...{Colors.ENDC}")
    try:
        editor_cmd = shlex.split(editor) + [str(config_file)]
        subprocess.run(editor_cmd, check=True)
    except FileNotFoundError:
        print(f"{Colors.FAIL}Error: Editor '{editor.split()[0]}' not found{Colors.ENDC}")
        print(f"Set the EDITOR environment variable to your preferred editor")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        print(f"{Colors.FAIL}Error: Editor exited with code {e.returncode}{Colors.ENDC}")
        raise typer.Exit(1)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help=f"Config key ({', '.join(CONFIG_SETTABLE_KEYS)})"),
    value: str = typer.Argument(..., help="Value to set (empty string to clear)"),
):
    """Set a config value."""
    init_colors()
    if key not in CONFIG_SETTABLE_KEYS:
        print(f"{Colors.FAIL}Error: Unknown config key '{key}'{Colors.ENDC}")
        print(f"{Colors.CYAN}Valid keys:{Colors.ENDC}")
        for k, desc in CONFIG_SETTABLE_KEYS.items():
            print(f"  {k:30s} {desc}")
        raise typer.Exit(1)

    config = load_config()

    if '.' in key:
        section, subkey = key.split('.', 1)
        if value == '':
            if section in config:
                config[section].pop(subkey, None)
        else:
            config.setdefault(section, {})[subkey] = value
    else:
        if value == '':
            config.pop(key, None)
        else:
            config[key] = value

    if save_config(config):
        if value == '':
            print(f"{Colors.GREEN}Cleared '{key}'{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}Set '{key}' = {value}{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}Error: Failed to save config{Colors.ENDC}")
        raise typer.Exit(1)


@config_app.command("add-repo")
def config_add_repo(
    name: Optional[str] = typer.Argument(None, help="Repo name (auto-detects from cwd if omitted)"),
):
    """Add a repo to the configured repos list."""
    init_colors()
    if name is None or (isinstance(name, str) and name == ''):
        try:
            repos_parent = str(get_repos_parent())
        except TemplatesDirNotFound:
            print(f"{Colors.FAIL}Error: Cannot auto-detect repo without repos_parent configured{Colors.ENDC}")
            print(f"Either specify a repo name or run {Colors.CYAN}bt config set repos_parent <path>{Colors.ENDC} first")
            raise typer.Exit(1)
        repo_name = detect_current_repo(repos_parent)
        if not repo_name:
            print(f"{Colors.FAIL}Error: Could not detect current repo from working directory{Colors.ENDC}")
            print(f"Run from within a repo directory, or specify: bt config add-repo <name>")
            raise typer.Exit(1)
    else:
        repo_name = os.path.basename(os.path.normpath(name))

    config = load_config()
    repos = config.get('repos', [])

    if repo_name in repos:
        print(f"{Colors.BLUE}'{repo_name}' is already in configured repos{Colors.ENDC}")
    else:
        repos.append(repo_name)
        config['repos'] = repos
        if save_config(config):
            print(f"{Colors.GREEN}Added '{repo_name}' to configured repos{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}Error: Failed to save config file{Colors.ENDC}")
            raise typer.Exit(1)

    print(f"\n{Colors.CYAN}Configured repos:{Colors.ENDC}")
    for r in repos:
        print(f"  - {r}")


@config_app.command("remove-repo")
def config_remove_repo(
    name: str = typer.Argument(..., help="Repo name to remove"),
):
    """Remove a repo from the configured repos list."""
    init_colors()
    config = load_config()
    repos = config.get('repos', [])

    if name in repos:
        repos.remove(name)
        config['repos'] = repos
        if save_config(config):
            print(f"{Colors.GREEN}Removed '{name}' from configured repos{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}Error: Failed to save config file{Colors.ENDC}")
            raise typer.Exit(1)
    else:
        print(f"{Colors.WARNING}'{name}' is not in configured repos{Colors.ENDC}")

    print(f"\n{Colors.CYAN}Configured repos:{Colors.ENDC}")
    for r in repos:
        print(f"  - {r}")


@config_app.command("init")
def config_init(
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
):
    """Interactive first-run configuration setup."""
    init_colors()
    config_file = get_config_file()

    if config_file.exists():
        print(f"{Colors.BLUE}Config already exists: {config_file}{Colors.ENDC}")
        config = load_config()
        print(json.dumps(config, indent=2))
        if non_interactive:
            raise typer.Exit()
        overwrite = questionary.confirm("Overwrite existing config?", default=False).ask()
        if not overwrite:
            raise typer.Exit()

    config = {'repos': []}

    if non_interactive:
        print(f"{Colors.FAIL}Error: Interactive setup requires a terminal{Colors.ENDC}")
        print(f"Use {Colors.CYAN}bt config set <key> <value>{Colors.ENDC} instead")
        raise typer.Exit(1)

    # repos_parent
    default_parent = '~/repos' if not is_windows() else ''
    repos_parent_str = questionary.text(
        "Parent directory containing your mod repos:",
        default=default_parent,
    ).ask()
    if repos_parent_str is None:
        raise typer.Exit()
    if repos_parent_str:
        config['repos_parent'] = repos_parent_str

        # Auto-detect repos
        expanded = os.path.expanduser(repos_parent_str)
        if os.path.isdir(expanded):
            dirs = sorted([
                d for d in os.listdir(expanded)
                if os.path.isdir(os.path.join(expanded, d)) and not d.startswith('.')
            ])
            if dirs:
                print(f"\n{Colors.CYAN}Found directories:{Colors.ENDC}")
                selected = questionary.checkbox(
                    "Select repos to add:",
                    choices=dirs,
                ).ask()
                if selected:
                    config['repos'] = selected

    # Namespace
    namespace = questionary.text(
        "Default Thunderstore namespace (author name):",
        default='',
    ).ask()
    if namespace:
        config.setdefault('defaults', {})['namespace'] = namespace

    # Website URL
    website = questionary.text(
        "Default website URL (e.g., GitHub repo URL):",
        default='',
    ).ask()
    if website:
        config.setdefault('defaults', {})['website_url'] = website

    # Release directory
    release_dir = questionary.text(
        "Central release directory (leave empty to skip):",
        default='',
    ).ask()
    if release_dir:
        config['release_dir'] = release_dir

    if save_config(config):
        print(f"\n{Colors.GREEN}Config saved to: {config_file}{Colors.ENDC}")
        print(json.dumps(config, indent=2))
    else:
        print(f"{Colors.FAIL}Error: Failed to save config{Colors.ENDC}")
        raise typer.Exit(1)


def _interactive_config(repos_parent: Optional[str]):
    """Handle config management from the interactive menu."""
    sub = questionary.select(
        "Configuration action:",
        choices=[
            "Show current config",
            "Run setup wizard",
            "Add a repo",
            "Remove a repo",
            "Edit config file",
        ]
    ).ask()
    if not sub:
        raise typer.Exit()

    if sub == "Show current config":
        config_show()
    elif sub == "Run setup wizard":
        config_init(non_interactive=False)
    elif sub == "Add a repo":
        repo_name = detect_current_repo(repos_parent) if repos_parent else None
        if repo_name:
            use_current = questionary.confirm(
                f"Add current repo '{repo_name}'?", default=True
            ).ask()
            if use_current:
                config_add_repo(name=repo_name)
                return
        name = questionary.text("Repo name:").ask()
        if name:
            config_add_repo(name=name)
    elif sub == "Remove a repo":
        repos = get_configured_repos()
        if not repos:
            print(f"{Colors.WARNING}No repos configured{Colors.ENDC}")
            return
        selection = questionary.select("Select repo to remove:", choices=repos).ask()
        if selection:
            config_remove_repo(name=selection)
    elif sub == "Edit config file":
        config_edit()


def run():
    """Entry point for the CLI."""
    app(prog_name="bt")
