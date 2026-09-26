"""The version lives in two places; the Windows bundle's release names and
the installer read __version__, and the tag must match both (checked in
windows-bundle.yml)."""

import tomllib
from pathlib import Path

import previously_on


def test_package_and_project_versions_agree():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert previously_on.__version__ == project["project"]["version"]
