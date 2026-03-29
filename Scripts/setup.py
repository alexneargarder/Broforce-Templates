"""Custom build that bundles templates from the repo root into the package.

When installed via pipx, templates are included as package data so the tool
works without needing access to the full Broforce-Templates repository.
"""
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

REPO_ROOT = Path(__file__).parent.parent

TEMPLATE_DIRS = [
    'Bro Template',
    'Mod Template',
    'Wardrobe Template',
    'ThunderstorePackage',
]

EXTRA_FILES = [
    ('Scripts/BroforceModBuild.targets', 'Scripts/BroforceModBuild.targets'),
]


class BuildPyWithTemplates(build_py):
    """Custom build_py that copies templates into the package before building."""

    def run(self):
        self._copy_templates()
        super().run()

    def _copy_templates(self):
        dest_base = Path('src/broforce_tools/templates')
        if not REPO_ROOT.is_dir():
            return

        for template_dir in TEMPLATE_DIRS:
            src = REPO_ROOT / template_dir
            dst = dest_base / template_dir
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(str(src), str(dst))

        for src_rel, dst_rel in EXTRA_FILES:
            src = REPO_ROOT / src_rel
            dst = dest_base / dst_rel
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))


setup(
    cmdclass={'build_py': BuildPyWithTemplates},
)
