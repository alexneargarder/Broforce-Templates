"""CLI application using Typer."""
import filecmp
import json
import os
import re
import shutil
import tempfile
import zipfile
from typing import Optional

import questionary
import typer

from .colors import Colors, init_colors
from .config import get_configured_repos, load_config, save_config, get_defaults
from .paths import get_repos_parent, get_templates_dir, get_cache_dir
from .templates import (
    copyanything,
    detect_current_repo,
    detect_project_type,
    find_mod_metadata_dir,
    find_projects,
    find_replace,
    get_releases_path,
    get_repos_to_search,
    get_source_directory,
    rename_files,
)
from .thunderstore import (
    add_changelog_entry,
    clear_cache,
    compare_versions,
    detect_dependencies_from_csproj,
    find_changelog,
    find_dll_in_modcontent,
    get_cache_file,
    get_dependencies,
    get_dependency_versions,
    get_latest_version_entries,
    get_unreleased_entries,
    get_version_from_changelog,
    get_version_from_info_json,
    has_unreleased_version,
    sanitize_package_name,
    sync_version_file,
    validate_package_name,
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
    repos_parent = str(get_repos_parent())
    repos = _get_repos_for_completion(repos_parent)
    projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
    return [_escape_for_completion(p[0]) for p in projects]


def _complete_project_names_with_metadata(incomplete: str) -> list[str]:
    """Autocompletion for project names (only projects with Thunderstore metadata)."""
    repos_parent = str(get_repos_parent())
    repos = _get_repos_for_completion(repos_parent)
    projects = find_projects(repos_parent, repos, require_metadata=True)
    return [_escape_for_completion(p[0]) for p in projects]


def _complete_project_type(incomplete: str) -> list[str]:
    """Autocompletion for project type (mod or bro)."""
    types = ["mod", "bro"]
    return [t for t in types if t.startswith(incomplete.lower())]


def _complete_repos(incomplete: str) -> list[str]:
    """Autocompletion for repository names."""
    config = load_config()
    repos = config.get('repos', [])
    return [r for r in repos if r.lower().startswith(incomplete.lower())]


def _complete_none(incomplete: str) -> list[str]:
    """Return empty list to prevent file completion fallback."""
    return []


def check_missing_required(missing: list[tuple[str, str]]) -> None:
    """Error if any required values are missing in non-interactive mode."""
    if missing:
        print(f"{Colors.FAIL}Error: Non-interactive mode requires the following:{Colors.ENDC}")
        for flag, desc in missing:
            print(f"  {flag}: {desc}")
        print(f"\nRun without --non-interactive for interactive prompts, or provide the missing options.")
        raise typer.Exit(1)


def select_projects_interactive(
    repos_parent: str,
    mode: str,
    use_all_repos: bool = False,
    allow_batch: bool = True
) -> list[tuple[str, str]]:
    """Interactive project selection for commands."""
    repos, is_single_repo = get_repos_to_search(repos_parent, use_all_repos)
    if not repos:
        print(f"{Colors.FAIL}Error: No repos configured. Use --add-repo to add repos.{Colors.ENDC}")
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
        project_name, repo = projects[0]
        print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        return [projects[0]]

    if allow_batch:
        choices = [f"{batch_label} ({len(projects)} projects)"]
    else:
        choices = []

    if is_single_repo:
        choices.extend([name for name, repo in projects])
    else:
        choices.extend([f"{name} ({repo})" for name, repo in projects])

    prompt = f"Select project:" if not is_single_repo else f"Select project from {repos[0]}:"
    selection = questionary.select(prompt, choices=choices).ask()

    if not selection:
        return []

    if allow_batch and selection.startswith(batch_label.split()[0]):
        return projects

    if is_single_repo:
        return [(selection, repos[0])]
    else:
        project_name = selection.rsplit(' (', 1)[0]
        for p in projects:
            if p[0] == project_name:
                return [p]
        return []


def do_init_thunderstore(
    project_name: str,
    repos_parent: str,
    namespace: Optional[str] = None,
    description: Optional[str] = None,
    website_url: Optional[str] = None,
    package_name_override: Optional[str] = None,
    non_interactive: bool = False,
) -> None:
    """Initialize Thunderstore metadata for an existing project."""
    print(f"{Colors.HEADER}Initializing Thunderstore metadata for '{project_name}'{Colors.ENDC}")

    template_dir = get_templates_dir()

    repos = [d for d in os.listdir(repos_parent) if os.path.isdir(os.path.join(repos_parent, d))]

    project_path = None
    releases_path = None
    output_repo = None

    for repo in repos:
        repo_path = os.path.join(repos_parent, repo)
        potential_project = os.path.join(repo_path, project_name)

        if os.path.exists(potential_project) and os.path.isdir(potential_project):
            project_path = potential_project
            releases_path = get_releases_path(repos_parent, repo, project_name, create=True)
            output_repo = repo
            break

    if not project_path or not releases_path:
        print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
        print(f"Searched in: {repos_parent}")
        raise typer.Exit(1)

    print(f"{Colors.BLUE}Found project in: {output_repo}{Colors.ENDC}")

    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type (no metadata folder or missing Info.json/*.mod.json){Colors.ENDC}")
        raise typer.Exit(1)

    print(f"{Colors.BLUE}Detected project type: {project_type}{Colors.ENDC}")

    defaults = get_defaults()
    default_namespace = defaults.get('namespace', '')
    default_website = defaults.get('website_url', '')

    # Collect missing required values for non-interactive mode
    missing: list[tuple[str, str]] = []

    # Namespace
    if namespace is not None:
        final_namespace = namespace
    elif non_interactive:
        if default_namespace:
            final_namespace = default_namespace
        else:
            missing.append(("--namespace / -n", "Thunderstore namespace/author"))
            final_namespace = ""
    else:
        print(f"\n{Colors.HEADER}Enter Thunderstore package information:{Colors.ENDC}")
        if default_namespace:
            final_namespace = questionary.text(
                f"Namespace/Author [{default_namespace}]:",
                default=default_namespace,
                validate=lambda text: validate_package_name(text)[0] if text else True
            ).ask()
            if final_namespace is None:
                raise typer.Exit()
            if not final_namespace:
                final_namespace = default_namespace
        else:
            final_namespace = questionary.text(
                "Namespace/Author (e.g., AlexNeargarder):",
                validate=lambda text: validate_package_name(text)[0]
            ).ask()
            if final_namespace is None or not final_namespace:
                raise typer.Exit()

    # Package name
    suggested_name = sanitize_package_name(project_name)
    if package_name_override is not None:
        final_package_name = package_name_override
    elif non_interactive:
        final_package_name = suggested_name
    else:
        final_package_name = questionary.text(
            f"Package name [{suggested_name}]:",
            default=suggested_name,
            validate=lambda text: validate_package_name(text)[0] if text else True
        ).ask()
        if final_package_name is None:
            raise typer.Exit()
        if not final_package_name:
            final_package_name = suggested_name

    # Description
    if description is not None:
        final_description = description
    elif non_interactive:
        missing.append(("--description / -d", "Package description (max 250 chars)"))
        final_description = ""
    else:
        final_description = questionary.text("Description (max 250 chars):").ask()
        if final_description is None:
            raise typer.Exit()

    if len(final_description) > 250:
        print(f"{Colors.WARNING}Warning: Description truncated to 250 characters{Colors.ENDC}")
        final_description = final_description[:250]

    # Website URL
    if website_url is not None:
        final_website_url = website_url
    elif non_interactive:
        final_website_url = default_website
    else:
        if default_website:
            final_website_url = questionary.text(
                f"Website/GitHub URL [{default_website}]:",
                default=default_website
            ).ask()
            if final_website_url is None:
                raise typer.Exit()
            if not final_website_url:
                final_website_url = default_website
        else:
            final_website_url = questionary.text("Website/GitHub URL:").ask()
            if final_website_url is None:
                raise typer.Exit()
            final_website_url = final_website_url or ""

    # Check for missing required values in non-interactive mode
    check_missing_required(missing)

    # Create releases directory if it doesn't exist
    os.makedirs(releases_path, exist_ok=True)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        changelog_path = os.path.join(releases_path, 'Changelog.md')
        print(f"{Colors.WARNING}Changelog not found, creating default{Colors.ENDC}")
        with open(changelog_path, 'w', encoding='utf-8') as f:
            f.write('## v1.0.0 (unreleased)\n- Initial release\n')

    detected_deps = detect_dependencies_from_csproj(project_path)
    dependencies = get_dependencies()
    if len(detected_deps) > 1:
        print(f"{Colors.BLUE}Detected dependencies:{Colors.ENDC}")
        for dep in detected_deps:
            if dep != dependencies['UMM']:
                print(f"  - {dep}")

    manifest_path = os.path.join(releases_path, 'manifest.json')
    manifest_data = {
        "name": final_package_name,
        "author": final_namespace,
        "version_number": "1.0.0",
        "website_url": final_website_url,
        "description": final_description,
        "dependencies": detected_deps
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=2)

    print(f"{Colors.GREEN}Created manifest.json{Colors.ENDC}")

    readme_template = os.path.join(template_dir, 'ThunderstorePackage', 'README.md')
    readme_dest = os.path.join(releases_path, 'README.md')

    if os.path.exists(readme_dest):
        print(f"{Colors.BLUE}README.md already exists, skipping{Colors.ENDC}")
    elif os.path.exists(readme_template):
        with open(readme_template, 'r', encoding='utf-8') as f:
            readme_content = f.read()

        readme_content = readme_content.replace('PROJECT_NAME', project_name)
        readme_content = readme_content.replace('DESCRIPTION_PLACEHOLDER', final_description)
        readme_content = readme_content.replace('FEATURES_PLACEHOLDER', '*Describe your mod\'s features here*')
        readme_content = readme_content.replace('WEBSITE_URL', final_website_url)

        with open(readme_dest, 'w', encoding='utf-8') as f:
            f.write(readme_content)

        print(f"{Colors.GREEN}Created README.md{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: README template not found at {readme_template}{Colors.ENDC}")

    icon_template = os.path.join(template_dir, 'ThunderstorePackage', 'icon.png')
    icon_dest = os.path.join(releases_path, 'icon.png')

    if os.path.exists(icon_dest):
        print(f"{Colors.BLUE}icon.png already exists, skipping{Colors.ENDC}")
    elif os.path.exists(icon_template):
        shutil.copy2(icon_template, icon_dest)
        print(f"{Colors.GREEN}Created icon.png{Colors.ENDC}")
        print(f"{Colors.WARNING}⚠️  Replace icon.png with a custom 256x256 image!{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: Icon template not found at {icon_template}{Colors.ENDC}")

    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Thunderstore metadata initialized!{Colors.ENDC}")
    print(f"{Colors.CYAN}Location:{Colors.ENDC} {releases_path}")
    print(f"\n{Colors.CYAN}Files created:{Colors.ENDC}")
    print(f"  - manifest.json")
    print(f"  - README.md (customize for Thunderstore)")
    print(f"  - icon.png (⚠️  placeholder - replace with 256x256 custom icon!)")
    print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
    print(f"  1. Edit {releases_path}/README.md")
    print(f"  2. Replace icon.png with custom icon")
    print(f"  3. Review manifest.json dependencies")
    print(f"  4. Run: bt package \"{project_name}\"")


def do_package(
    project_name: str,
    repos_parent: str,
    version_override: Optional[str] = None,
    non_interactive: bool = False,
    allow_outdated_changelog: bool = False,
    overwrite: bool = False,
    update_deps: Optional[bool] = None,
    add_missing_deps: Optional[bool] = None,
) -> None:
    """Create Thunderstore package for an existing project."""
    template_dir = get_templates_dir()

    repos = [d for d in os.listdir(repos_parent) if os.path.isdir(os.path.join(repos_parent, d))]
    project_path = None
    releases_path = None
    output_repo = None

    for repo in repos:
        repo_path = os.path.join(repos_parent, repo)
        potential_project = os.path.join(repo_path, project_name)

        if os.path.exists(potential_project) and os.path.isdir(potential_project):
            releases_path = get_releases_path(repos_parent, repo, project_name, create=False)
            if releases_path:
                project_path = potential_project
                output_repo = repo
                break

    if not project_path or not releases_path:
        print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    manifest_path = os.path.join(releases_path, 'manifest.json')
    readme_path = os.path.join(releases_path, 'README.md')
    icon_path = os.path.join(releases_path, 'icon.png')
    changelog_path = find_changelog(releases_path)

    if not os.path.exists(manifest_path):
        print(f"{Colors.FAIL}Error: manifest.json not found{Colors.ENDC}")
        print(f"Run: bt init-thunderstore \"{project_name}\"")
        raise typer.Exit(1)

    if not os.path.exists(readme_path):
        print(f"{Colors.FAIL}Error: README.md not found{Colors.ENDC}")
        raise typer.Exit(1)

    if not os.path.exists(icon_path):
        print(f"{Colors.FAIL}Error: icon.png not found{Colors.ENDC}")
        raise typer.Exit(1)

    if not changelog_path:
        print(f"{Colors.FAIL}Error: Changelog.md or CHANGELOG.md not found{Colors.ENDC}")
        raise typer.Exit(1)

    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type{Colors.ENDC}")
        raise typer.Exit(1)

    metadata_dir = find_mod_metadata_dir(project_path)
    if not metadata_dir:
        print(f"{Colors.FAIL}Error: Could not find metadata folder{Colors.ENDC}")
        raise typer.Exit(1)

    dll_path = find_dll_in_modcontent(metadata_dir)

    if not dll_path:
        print(f"{Colors.FAIL}Error: No DLL found in metadata folder{Colors.ENDC}")
        print(f"Build the project first")
        raise typer.Exit(1)

    icon_template = os.path.join(template_dir, 'ThunderstorePackage', 'icon.png')
    if os.path.exists(icon_template) and filecmp.cmp(icon_path, icon_template, shallow=False):
        print(f"{Colors.WARNING}⚠️  Warning: Using placeholder icon{Colors.ENDC}")

    changelog_name = os.path.basename(changelog_path)

    if version_override:
        version = version_override
        print(f"{Colors.CYAN}Using version override: {version}{Colors.ENDC}")
    else:
        changelog_version = get_version_from_changelog(changelog_path)
        manifest_version = None
        info_version = None

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data_temp = json.load(f)
            manifest_version = manifest_data_temp.get('version_number', None)
        except Exception:
            pass

        info_version = get_version_from_info_json(metadata_dir, project_type)

        versions = {
            changelog_name: changelog_version,
            'manifest.json': manifest_version,
            'Info.json/.mod.json': info_version
        }

        valid_versions = {k: v for k, v in versions.items() if v is not None}

        if not valid_versions:
            print(f"{Colors.FAIL}Error: Could not find version in any file{Colors.ENDC}")
            print(f"Expected version in {changelog_name}, manifest.json, or Info.json/.mod.json")
            raise typer.Exit(1)

        highest_version = None
        highest_source = None
        for source, ver in valid_versions.items():
            if highest_version is None or compare_versions(ver, highest_version) > 0:
                highest_version = ver
                highest_source = source

        version = highest_version

        print(f"{Colors.CYAN}Package version: {version}{Colors.ENDC}")

        if changelog_version and compare_versions(changelog_version, version) < 0:
            print(f"\n{Colors.WARNING}Warning: {changelog_name} is out of date!{Colors.ENDC}")
            print(f"{Colors.CYAN}Changelog version: {changelog_version}{Colors.ENDC}")
            print(f"{Colors.CYAN}Highest version found: {version} (from {highest_source}){Colors.ENDC}")
            print(f"\n{Colors.WARNING}Did you forget to update {changelog_name}?{Colors.ENDC}")

            if non_interactive:
                if not allow_outdated_changelog:
                    print(f"\n{Colors.FAIL}Error: Changelog is outdated. Use --allow-outdated-changelog to package anyway.{Colors.ENDC}")
                    raise typer.Exit(1)
            else:
                continue_package = questionary.confirm(
                    f"Continue packaging with version {version}?",
                    default=False
                ).ask()

                if continue_package is None or not continue_package:
                    print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
                    print(f"Update {changelog_name} to version {version} before packaging.")
                    raise typer.Exit()

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest_data = json.load(f)

    namespace = manifest_data.get('author', 'Unknown')
    package_name = manifest_data.get('name', project_name.replace(' ', '_'))

    if namespace == 'Unknown' or not namespace:
        print(f"\n{Colors.WARNING}Warning: No author/namespace set in manifest.json{Colors.ENDC}")
        print(f"{Colors.CYAN}The author field is used for the package filename and Thunderstore namespace.{Colors.ENDC}")

        if non_interactive:
            print(f"\n{Colors.FAIL}Error: No author set in manifest.json. Edit manifest.json to add an author.{Colors.ENDC}")
            raise typer.Exit(1)

        set_author = questionary.confirm(
            "Set author name now?",
            default=True
        ).ask()

        if set_author is None:
            raise typer.Exit()
        elif set_author:
            namespace = questionary.text(
                "Enter namespace/author (alphanumeric + underscores only):",
                validate=lambda text: validate_package_name(text)[0]
            ).ask()

            if namespace is None:
                raise typer.Exit()

            manifest_data['author'] = namespace
            print(f"{Colors.GREEN}Author set to: {namespace}{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}Continuing with 'Unknown' as author (package will be named Unknown-{package_name}-{version}.zip){Colors.ENDC}")

    dependencies = get_dependencies()
    current_deps = manifest_data.get('dependencies', [])
    outdated_deps = []
    updated_deps = []

    for dep in current_deps:
        parts = dep.rsplit('-', 1)
        if len(parts) == 2:
            dep_name_part, dep_version = parts
            for dep_key, current_dep_string in dependencies.items():
                if current_dep_string.startswith(dep_name_part + '-'):
                    if dep != current_dep_string:
                        outdated_deps.append((dep, current_dep_string))
                        updated_deps.append(current_dep_string)
                    else:
                        updated_deps.append(dep)
                    break
            else:
                updated_deps.append(dep)
        else:
            updated_deps.append(dep)

    if outdated_deps:
        print(f"\n{Colors.WARNING}Outdated dependencies detected:{Colors.ENDC}")
        for old_dep, new_dep in outdated_deps:
            print(f"  {old_dep} → {new_dep}")

        if non_interactive:
            # Default to True in non-interactive mode unless explicitly set to False
            should_update = update_deps if update_deps is not None else True
        else:
            update = questionary.confirm(
                "Update dependencies to latest versions?",
                default=True
            ).ask()

            if update is None:
                raise typer.Exit()
            should_update = update

        if should_update:
            manifest_data['dependencies'] = updated_deps
            print(f"{Colors.GREEN}Dependencies updated{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}Keeping existing dependency versions{Colors.ENDC}")
    else:
        updated_deps = current_deps

    detected_deps = detect_dependencies_from_csproj(project_path)
    current_dep_set = set(updated_deps if updated_deps else current_deps)
    missing_deps = []

    for dep in detected_deps:
        if dep not in current_dep_set:
            missing_deps.append(dep)

    if missing_deps:
        print(f"\n{Colors.WARNING}Warning: Dependencies detected in .csproj but not in manifest.json:{Colors.ENDC}")
        for dep in missing_deps:
            print(f"  + {dep}")

        if non_interactive:
            # Default to True in non-interactive mode unless explicitly set to False
            should_add = add_missing_deps if add_missing_deps is not None else True
        else:
            add_deps_prompt = questionary.confirm(
                "Add missing dependencies to manifest?",
                default=True
            ).ask()

            if add_deps_prompt is None:
                raise typer.Exit()
            should_add = add_deps_prompt

        if should_add:
            if updated_deps:
                updated_deps.extend(missing_deps)
            else:
                updated_deps = list(current_dep_set) + missing_deps
            manifest_data['dependencies'] = updated_deps
            print(f"{Colors.GREEN}Missing dependencies added{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}Continuing without adding missing dependencies{Colors.ENDC}")

    old_manifest_version = manifest_data.get('version_number', None)
    manifest_data['version_number'] = version

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=2)

    if old_manifest_version != version:
        print(f"{Colors.GREEN}Updated manifest.json version to {version}{Colors.ENDC}")
    else:
        print(f"{Colors.BLUE}manifest.json already at version {version}{Colors.ENDC}")

    updated, version_file_path = sync_version_file(metadata_dir, project_type, version)
    if updated:
        version_file_name = os.path.basename(version_file_path)
        print(f"{Colors.GREEN}Updated {version_file_name} version to {version}{Colors.ENDC}")
    elif version_file_path:
        version_file_name = os.path.basename(version_file_path)
        print(f"{Colors.BLUE}{version_file_name} already at version {version}{Colors.ENDC}")
    else:
        version_file_name = 'Info.json' if project_type == 'mod' else '.mod.json'
        print(f"{Colors.WARNING}Warning: Could not find {version_file_name} to sync version{Colors.ENDC}")

    if project_type == 'bro' and version_file_path:
        try:
            with open(version_file_path, 'r', encoding='utf-8') as f:
                mod_json_data = json.load(f)

            current_bromaker_version = mod_json_data.get('BroMakerVersion', None)
            if current_bromaker_version:
                dep_versions = get_dependency_versions()
                latest_bromaker_version = dep_versions.get('BroMaker', current_bromaker_version)

                if current_bromaker_version != latest_bromaker_version:
                    print(f"\n{Colors.WARNING}Outdated BroMakerVersion in {os.path.basename(version_file_path)}:{Colors.ENDC}")
                    print(f"  {current_bromaker_version} → {latest_bromaker_version}")

                    if non_interactive:
                        # Auto-update in non-interactive mode
                        should_update_bromaker = True
                    else:
                        update_bromaker = questionary.confirm(
                            "Update BroMakerVersion to latest?",
                            default=True
                        ).ask()

                        if update_bromaker is None:
                            raise typer.Exit()
                        should_update_bromaker = update_bromaker

                    if should_update_bromaker:
                        mod_json_data['BroMakerVersion'] = latest_bromaker_version
                        with open(version_file_path, 'w', encoding='utf-8') as f:
                            json.dump(mod_json_data, f, indent=2)
                        print(f"{Colors.GREEN}Updated BroMakerVersion to {latest_bromaker_version}{Colors.ENDC}")
        except (json.JSONDecodeError, OSError):
            pass

    zip_filename = f"{namespace}-{package_name}-{version}.zip"
    zip_path = os.path.join(releases_path, zip_filename)

    if os.path.exists(zip_path):
        print(f"\n{Colors.WARNING}Package {zip_filename} already exists{Colors.ENDC}")

        if non_interactive:
            if not overwrite:
                print(f"\n{Colors.FAIL}Error: Package already exists. Use --overwrite to replace it.{Colors.ENDC}")
                raise typer.Exit(1)
            should_overwrite = True
        else:
            overwrite_prompt = questionary.confirm(
                "Overwrite existing package?",
                default=True
            ).ask()

            if overwrite_prompt is None:
                raise typer.Exit()
            should_overwrite = overwrite_prompt

        if not should_overwrite:
            print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
            print(f"To create a new package, update the version in {changelog_name}")
            raise typer.Exit()

        os.remove(zip_path)
        print(f"{Colors.BLUE}Removed existing package{Colors.ENDC}")
    else:
        old_zips = [f for f in os.listdir(releases_path) if f.endswith('.zip')]
        if old_zips:
            prev_versions_dir = os.path.join(releases_path, 'Previous Versions')
            if not os.path.exists(prev_versions_dir):
                os.makedirs(prev_versions_dir)

            for old_zip in old_zips:
                old_zip_path = os.path.join(releases_path, old_zip)
                new_zip_path = os.path.join(prev_versions_dir, old_zip)
                shutil.move(old_zip_path, new_zip_path)
                print(f"{Colors.BLUE}Archived: {old_zip}{Colors.ENDC}")

    print(f"{Colors.CYAN}Creating package: {zip_filename}{Colors.ENDC}")

    with tempfile.TemporaryDirectory() as temp_dir:
        shutil.copy2(manifest_path, os.path.join(temp_dir, 'manifest.json'))
        shutil.copy2(readme_path, os.path.join(temp_dir, 'README.md'))
        shutil.copy2(icon_path, os.path.join(temp_dir, 'icon.png'))

        with open(changelog_path, 'r', encoding='utf-8') as f:
            changelog_content = f.read()

        changelog_cleaned = re.sub(
            r'(##\s*v?\d+\.\d+\.\d+:?)\s*\(unreleased\)',
            r'\1',
            changelog_content,
            flags=re.IGNORECASE
        )

        if changelog_cleaned != changelog_content:
            with open(changelog_path, 'w', encoding='utf-8') as f:
                f.write(changelog_cleaned)
            print(f"{Colors.GREEN}Removed (unreleased) tag from {changelog_name}{Colors.ENDC}")

        with open(os.path.join(temp_dir, 'CHANGELOG.md'), 'w', encoding='utf-8') as f:
            f.write(changelog_cleaned)

        umm_base = os.path.join(temp_dir, 'UMM')
        if project_type == 'mod':
            target_dir = os.path.join(umm_base, 'Mods', project_name)
        else:
            target_dir = os.path.join(umm_base, 'BroMaker_Storage', project_name)

        os.makedirs(target_dir, exist_ok=True)

        copyanything(metadata_dir, target_dir)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

    zip_size = os.path.getsize(zip_path) / 1024

    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Package created!{Colors.ENDC}")
    print(f"{Colors.CYAN}Version:{Colors.ENDC} {version}")
    print(f"{Colors.CYAN}File:{Colors.ENDC} {zip_path}")
    print(f"{Colors.CYAN}Size:{Colors.ENDC} {zip_size:.1f} KB")
    print(f"\n{Colors.CYAN}Package ready for Thunderstore upload!{Colors.ENDC}")


def do_create_project(
    template_type: Optional[str],
    name: Optional[str],
    author: Optional[str],
    output_repo: Optional[str],
    non_interactive: bool = False,
    no_thunderstore: bool = False,
) -> None:
    """Create a new mod or bro project from templates."""
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
        missing.append(("--type / -t", "Project type (mod or bro)"))
    else:
        choice = questionary.select(
            "What would you like to create?",
            choices=["Mod", "Bro"]
        ).ask()

        if not choice:
            raise typer.Exit()

        template_type = choice.lower()

    if template_type == "mod":
        source_template_name = "Mod Template"
    elif template_type == "bro":
        source_template_name = "Bro Template"
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

    if output_repo_path != template_dir:
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

    releasesPath = os.path.join(output_repo_path, 'Releases')
    newReleaseFolder = os.path.join(releasesPath, newName)
    newRepoPath = os.path.join(output_repo_path, newName)

    if not os.path.exists(templatePath):
        print(f"{Colors.FAIL}Error: Template directory not found: {templatePath}{Colors.ENDC}")
        print(f"Please ensure the '{source_template_name}' directory exists in your repository.")
        raise typer.Exit(1)

    if not os.path.exists(releasesPath):
        try:
            os.makedirs(releasesPath)
            print(f"{Colors.GREEN}Created Releases directory: {releasesPath}{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}Error: Failed to create Releases directory: {e}{Colors.ENDC}")
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
        os.makedirs(newReleaseFolder)
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

        if template_type == "mod":
            rename_files(newRepoPath, 'ModTemplate', newNameNoSpaces)
        else:
            rename_files(newRepoPath, 'BroTemplate', newNameNoSpaces)

        if template_type == "mod":
            fileTypes = ["*.csproj", "*.cs", "*.sln", "*.json", "*.xml"]
        else:
            fileTypes = ["*.csproj", "*.cs", "*.sln", "*.json"]

        for fileType in fileTypes:
            find_replace(newRepoPath, source_template_name, newName, fileType)
            find_replace(newRepoPath, source_template_name.replace(' ', '_'), newNameWithUnderscore, fileType)
            if template_type == "mod":
                find_replace(newRepoPath, "ModTemplate", newNameNoSpaces, fileType)
            else:
                find_replace(newRepoPath, "BroTemplate", newNameNoSpaces, fileType)

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
            print(f"  1. Open the project in Visual Studio")
            print(f"  2. Build the project (builds to game automatically)")
            print(f"  3. Launch Broforce to test your {template_type}")
            print(f"  4. Run 'bt init-thunderstore' when ready to publish")
        elif non_interactive:
            # In non-interactive mode without --no-thunderstore, skip init (can't prompt for metadata)
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
                do_init_thunderstore(newName, repos_parent)
            else:
                print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
                print(f"  1. Open the project in Visual Studio")
                print(f"  2. Build the project (builds to game automatically)")
                print(f"  3. Launch Broforce to test your {template_type}")
                print(f"  4. Run 'bt init-thunderstore' when ready to publish")

    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed during file processing: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    clear_cache_flag: bool = typer.Option(False, "--clear-cache", help="Clear dependency version cache"),
    add_repo: Optional[str] = typer.Option(None, "--add-repo", help="Add repo to config (uses current if empty string)", autocompletion=_complete_none),
):
    """Tool for creating Broforce mods and packaging for Thunderstore."""
    init_colors()
    repos_parent = str(get_repos_parent())

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

    if add_repo is not None:
        if add_repo == '':
            repo_name = detect_current_repo(repos_parent)
            if not repo_name:
                print(f"{Colors.FAIL}Error: Could not detect current repo from working directory{Colors.ENDC}")
                print(f"Run from within a repo directory, or specify repo name: --add-repo RepoName")
                raise typer.Exit(1)
        else:
            repo_name = add_repo

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
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        print(f"{Colors.HEADER}Broforce Mod Tools{Colors.ENDC}\n")

        choice = questionary.select(
            "What would you like to do?",
            choices=[
                "Create new mod / bro project",
                "Setup Thunderstore metadata for an existing project",
                "Package for releasing on Thunderstore",
                "View/package unreleased projects",
                "Show help"
            ]
        ).ask()

        if not choice:
            raise typer.Exit()

        if choice == "Show help":
            print(ctx.get_help())
            raise typer.Exit()
        elif choice == "Create new mod / bro project":
            do_create_project(None, None, None, None)
        elif choice == "Setup Thunderstore metadata for an existing project":
            selected = select_projects_interactive(repos_parent, 'init', use_all_repos=False)
            if not selected:
                raise typer.Exit()
            for project_name, repo in selected:
                if len(selected) > 1:
                    print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
                do_init_thunderstore(project_name, repos_parent)
        elif choice == "Package for releasing on Thunderstore":
            selected = select_projects_interactive(repos_parent, 'package', use_all_repos=False)
            if not selected:
                raise typer.Exit()
            for project_name, repo in selected:
                if len(selected) > 1:
                    print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
                do_package(project_name, repos_parent, None)
        elif choice == "View/package unreleased projects":
            ctx.invoke(unreleased)


@app.command()
def create(
    type: Optional[str] = typer.Option(None, "-t", "--type", help="Project type: mod or bro", autocompletion=_complete_project_type),
    name: Optional[str] = typer.Option(None, "-n", "--name", help="Project name", autocompletion=_complete_none),
    author: Optional[str] = typer.Option(None, "-a", "--author", help="Author name", autocompletion=_complete_none),
    output_repo: Optional[str] = typer.Option(None, "-o", "--output-repo", help="Target repository", autocompletion=_complete_repos),
    non_interactive: bool = typer.Option(False, "-y", "--non-interactive", help="Fail instead of prompting for input"),
    no_thunderstore: bool = typer.Option(False, "--no-thunderstore", help="Skip Thunderstore metadata setup"),
):
    """Create a new mod or bro project from templates."""
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
        do_init_thunderstore(
            project_name, repos_parent,
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
        for proj_name, _ in selected:
            if len(selected) > 1:
                print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
            do_init_thunderstore(
                proj_name, repos_parent,
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
):
    """Create a Thunderstore-ready ZIP package."""
    init_colors()
    repos_parent = str(get_repos_parent())

    # In non-interactive mode, project_name is required
    if non_interactive and not project_name:
        print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
        raise typer.Exit(1)

    if project_name:
        do_package(
            project_name, repos_parent, version,
            non_interactive=non_interactive,
            allow_outdated_changelog=allow_outdated_changelog,
            overwrite=overwrite,
            update_deps=update_deps,
            add_missing_deps=add_missing_deps,
        )
    else:
        selected = select_projects_interactive(repos_parent, 'package', use_all_repos=all_repos)
        if not selected:
            raise typer.Exit()
        for proj_name, _ in selected:
            if len(selected) > 1:
                print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
            do_package(
                proj_name, repos_parent, version,
                non_interactive=non_interactive,
                allow_outdated_changelog=allow_outdated_changelog,
                overwrite=overwrite,
                update_deps=update_deps,
                add_missing_deps=add_missing_deps,
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
        print(f"{Colors.FAIL}Error: No repos configured. Use --add-repo to add repos.{Colors.ENDC}")
        raise typer.Exit(1)

    projects = find_projects(repos_parent, repos, require_metadata=True)
    if not projects:
        print(f"{Colors.CYAN}No projects with Thunderstore metadata found.{Colors.ENDC}")
        raise typer.Exit()

    unreleased_by_repo: dict[str, list[tuple[str, str, list[str]]]] = {}

    for project_name, repo in projects:
        releases_path = get_releases_path(repos_parent, repo, project_name, create=False)
        if not releases_path:
            continue

        changelog_path = find_changelog(releases_path)
        if not changelog_path:
            continue

        is_unreleased, version = has_unreleased_version(changelog_path)
        if is_unreleased:
            _, entries = get_unreleased_entries(changelog_path)
            if repo not in unreleased_by_repo:
                unreleased_by_repo[repo] = []
            unreleased_by_repo[repo].append((project_name, version, entries))

    if not unreleased_by_repo:
        print(f"{Colors.CYAN}No projects with unreleased changes found.{Colors.ENDC}")
        raise typer.Exit()

    def print_unreleased_list(show_details: bool):
        print(f"{Colors.HEADER}Projects with unreleased changes:{Colors.ENDC}\n")
        all_projects = []
        for repo in sorted(unreleased_by_repo.keys()):
            print(f"{Colors.BLUE}{repo}:{Colors.ENDC}")
            for project_name, version, entries in sorted(unreleased_by_repo[repo]):
                print(f"  {project_name} (v{version})")
                all_projects.append((project_name, repo))
                if show_details and entries:
                    for entry in entries:
                        print(f"    {Colors.CYAN}{entry}{Colors.ENDC}")
            print()
        return all_projects

    # Build list of all unreleased projects
    all_unreleased: list[tuple[str, str]] = []
    for repo in sorted(unreleased_by_repo.keys()):
        for project_name, version, entries in sorted(unreleased_by_repo[repo]):
            all_unreleased.append((project_name, repo))

    # Handle non-interactive mode
    if non_interactive or package_all or package:
        print_unreleased_list(False)

        if package_all:
            # Package all unreleased
            for project_name, repo in all_unreleased:
                print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
                do_package(project_name, repos_parent, None, non_interactive=True)
        elif package:
            # Package specified projects
            project_names = {name for name, repo in all_unreleased}
            for proj in package:
                if proj not in project_names:
                    print(f"{Colors.WARNING}Warning: '{proj}' not found in unreleased projects, skipping{Colors.ENDC}")
                    continue
                # Find the repo for this project
                for p_name, p_repo in all_unreleased:
                    if p_name == proj:
                        print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
                        do_package(proj, repos_parent, None, non_interactive=True)
                        break
        # If just -y with no --package-all or --package, just list (already printed above)
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
        for project_name, repo in all_unreleased:
            print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
            do_package(project_name, repos_parent, None)
    else:
        if is_single_repo:
            project_choices = [name for name, _ in all_unreleased]
        else:
            project_choices = [f"{name} ({repo})" for name, repo in all_unreleased]

        selected = questionary.checkbox(
            "Select projects to package:",
            choices=project_choices
        ).ask()

        if not selected:
            print(f"{Colors.CYAN}No projects selected.{Colors.ENDC}")
            raise typer.Exit()

        for sel in selected:
            if is_single_repo:
                project_name = sel
                proj_repo = repos[0]
            else:
                project_name = sel.rsplit(' (', 1)[0]
                proj_repo = None
                for p_name, p_repo in all_unreleased:
                    if p_name == project_name:
                        proj_repo = p_repo
                        break

            print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
            do_package(project_name, repos_parent, None)


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
            print(f"{Colors.FAIL}Error: No repos configured. Use --add-repo to add repos.{Colors.ENDC}")
            raise typer.Exit(1)

        projects = find_projects(repos_parent, repos, require_metadata=True)
        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
            raise typer.Exit(1)

        if len(projects) == 1:
            project_name, repo = projects[0]
            print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        elif non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires specifying project name.{Colors.ENDC}")
            print(f"Usage: bt changelog add \"ProjectName\" \"Message\"")
            print(f"\nAvailable projects:")
            for name, r in projects:
                print(f"  - {name}")
            raise typer.Exit(1)
        else:
            choices = [f"{name} ({repo})" for name, repo in projects]
            selection = questionary.select("Select project:", choices=choices).ask()
            if not selection:
                raise typer.Exit()
            project_name = selection.rsplit(' (', 1)[0]
            for p in projects:
                if p[0] == project_name:
                    repo = p[1]
                    break
    else:
        project_name = arg1
        message = arg2
        repo = None
        for r in os.listdir(repos_parent):
            repo_path = os.path.join(repos_parent, r)
            if os.path.isdir(repo_path):
                potential_project = os.path.join(repo_path, project_name)
                if os.path.exists(potential_project) and os.path.isdir(potential_project):
                    repo = r
                    break
        if not repo:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)

    releases_path = get_releases_path(repos_parent, repo, project_name, create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    is_unreleased, version = has_unreleased_version(changelog_path)
    if not is_unreleased:
        print(f"{Colors.FAIL}Error: No unreleased version found in changelog{Colors.ENDC}")
        print(f"Add a version header like: ## v1.0.0 (unreleased)")
        raise typer.Exit(1)

    if add_changelog_entry(changelog_path, message):
        print(f"{Colors.GREEN}Added to {project_name} v{version}:{Colors.ENDC}")
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

    if project_name:
        repo = None
        for r in os.listdir(repos_parent):
            repo_path = os.path.join(repos_parent, r)
            if os.path.isdir(repo_path):
                potential_project = os.path.join(repo_path, project_name)
                if os.path.exists(potential_project) and os.path.isdir(potential_project):
                    repo = r
                    break
        if not repo:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)
    else:
        repos, _ = get_repos_to_search(repos_parent, all_repos)
        if not repos:
            print(f"{Colors.FAIL}Error: No repos configured. Use --add-repo to add repos.{Colors.ENDC}")
            raise typer.Exit(1)

        projects = find_projects(repos_parent, repos, require_metadata=True)
        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
            raise typer.Exit(1)

        if len(projects) == 1:
            project_name, repo = projects[0]
            print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        elif non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
            print(f"\nAvailable projects:")
            for name, r in projects:
                print(f"  - {name}")
            raise typer.Exit(1)
        else:
            choices = [f"{name} ({repo})" for name, repo in projects]
            selection = questionary.select("Select project:", choices=choices).ask()
            if not selection:
                raise typer.Exit()
            project_name = selection.rsplit(' (', 1)[0]
            for p in projects:
                if p[0] == project_name:
                    repo = p[1]
                    break

    releases_path = get_releases_path(repos_parent, repo, project_name, create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    editor = os.environ.get('EDITOR', os.environ.get('VISUAL', 'nano'))
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

    if project_name:
        repo = None
        for r in os.listdir(repos_parent):
            repo_path = os.path.join(repos_parent, r)
            if os.path.isdir(repo_path):
                potential_project = os.path.join(repo_path, project_name)
                if os.path.exists(potential_project) and os.path.isdir(potential_project):
                    repo = r
                    break
        if not repo:
            print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
            raise typer.Exit(1)
    else:
        repos, _ = get_repos_to_search(repos_parent, all_repos)
        if not repos:
            print(f"{Colors.FAIL}Error: No repos configured. Use --add-repo to add repos.{Colors.ENDC}")
            raise typer.Exit(1)

        projects = find_projects(repos_parent, repos, require_metadata=True)
        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found.{Colors.ENDC}")
            raise typer.Exit(1)

        if len(projects) == 1:
            project_name, repo = projects[0]
            print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        elif non_interactive:
            print(f"{Colors.FAIL}Error: Non-interactive mode requires a project name argument.{Colors.ENDC}")
            print(f"\nAvailable projects:")
            for name, r in projects:
                print(f"  - {name}")
            raise typer.Exit(1)
        else:
            # Check which projects have unreleased versions
            choices = []
            project_map = {}  # Map display string to (name, repo)
            unreleased_set = set()
            for name, r in projects:
                rel_path = get_releases_path(repos_parent, r, name, create=False)
                is_unreleased = False
                if rel_path:
                    cl_path = find_changelog(rel_path)
                    if cl_path:
                        is_unreleased, _ = has_unreleased_version(cl_path)
                if is_unreleased:
                    display = f"{name} ({r}) *"
                    unreleased_set.add(display)
                else:
                    display = f"{name} ({r})"
                choices.append(display)
                project_map[display] = (name, r)

            # Sort with unreleased projects first
            choices.sort(key=lambda x: (x not in unreleased_set, x))

            selection = questionary.select("Select project (* = unreleased):", choices=choices).ask()
            if not selection:
                raise typer.Exit()
            project_name, repo = project_map[selection]

    releases_path = get_releases_path(repos_parent, repo, project_name, create=False)
    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        print(f"{Colors.FAIL}Error: No changelog found for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    version, is_unreleased, entries = get_latest_version_entries(changelog_path)
    if not version:
        print(f"{Colors.CYAN}{project_name}: No versions found in changelog{Colors.ENDC}")
        raise typer.Exit()

    status = "(unreleased)" if is_unreleased else "(released)"
    print(f"{Colors.HEADER}{project_name} - v{version} {status}:{Colors.ENDC}")
    if entries:
        for entry in entries:
            print(f"  {entry}")
    else:
        print(f"  {Colors.CYAN}(no entries){Colors.ENDC}")


def run():
    """Entry point for the CLI."""
    app(prog_name="bt")
