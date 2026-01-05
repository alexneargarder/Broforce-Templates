#!/usr/bin/env python3
"""Helper for bash completion - minimal output for fast completion."""
import sys


def main():
    if len(sys.argv) < 2:
        return

    mode = sys.argv[1]

    from .config import load_config
    from .paths import get_repos_parent
    from .templates import find_projects

    config = load_config()
    repos_parent = str(get_repos_parent())
    repos = config.get('repos', [])

    if mode == 'repos':
        for repo in repos:
            print(repo)
    elif mode == 'init':
        projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
        for name, repo in projects:
            print(name)
    elif mode == 'package':
        projects = find_projects(repos_parent, repos, require_metadata=True)
        for name, repo in projects:
            print(name)


if __name__ == '__main__':
    main()
