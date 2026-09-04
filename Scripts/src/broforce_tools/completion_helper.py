#!/usr/bin/env python3
"""Helper for shell completion - minimal output for fast completion."""
import sys


def emit_completions(mode: str) -> None:
    """Print one completion candidate per line for the given mode."""
    from .config import load_config
    from .paths import get_repos_parent, TemplatesDirNotFound
    from .project import find_projects

    config = load_config()
    try:
        repos_parent = str(get_repos_parent())
    except TemplatesDirNotFound:
        return
    repos = config.get('repos', [])

    if mode == 'repos':
        for repo in repos:
            print(repo)
    elif mode == 'init':
        projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
        for project in projects:
            print(project.name)
    elif mode == 'package':
        projects = find_projects(repos_parent, repos, require_metadata=True)
        for project in projects:
            print(project.name)


def main():
    if len(sys.argv) < 2:
        return
    emit_completions(sys.argv[1])


if __name__ == '__main__':
    main()
