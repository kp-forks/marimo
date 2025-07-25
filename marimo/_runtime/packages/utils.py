# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import dataclasses
import os
import re
import sys
from typing import Optional

from marimo._utils.platform import is_pyodide


def in_virtual_environment() -> bool:
    """Returns True if a venv/virtualenv is activated"""
    # https://stackoverflow.com/questions/1871549/how-to-determine-if-python-is-running-inside-a-virtualenv/40099080#40099080  # noqa: E501
    base_prefix = (
        getattr(sys, "base_prefix", None)
        or getattr(sys, "real_prefix", None)
        or sys.prefix
    )
    return sys.prefix != base_prefix


def in_conda_env() -> bool:
    return "CONDA_DEFAULT_ENV" in os.environ


def is_dockerized() -> bool:
    return os.path.exists("/.dockerenv")


def is_modal_image() -> bool:
    return os.environ.get("MODAL_TASK_ID") is not None


def is_python_isolated() -> bool:
    """Returns True if not using system Python"""
    return (
        in_virtual_environment()
        or in_conda_env()
        or is_pyodide()
        or is_dockerized()
        or is_modal_image()
    )


def append_version(pkg_name: str, version: Optional[str]) -> str:
    """Qualify a version string with a leading '==' if it doesn't have one"""
    if version is None:
        return pkg_name
    if version == "":
        return pkg_name
    if version == "latest":
        return pkg_name
    return f"{pkg_name}=={version}"


def split_packages(package: str) -> list[str]:
    """
    Splits a package string into a list of packages.

    This can handle editable packages (i.e. local directories)

    e.g.
    "package1[extra1,extra2]==1.0.0" -> ["package1[extra1,extra2]==1.0.0"]
    "package1 package2" -> ["package1", "package2"]
    "package1==1.0.0 package2==2.0.0" -> ["package1==1.0.0", "package2==2.0.0"]
    "package1 -e /path/to/package1" -> ["package1 -e /path/to/package1"]
    "package1 --editable /path/to/package1" -> ["package1 --editable /path/to/package1"]
    "package1 -e /path/to/package1 package2" -> ["package1 -e /path/to/package1", "package2"]
    "package1 @ /path/to/package1" -> ["package1 @ /path/to/package1"]
    "foo==1.0; python_version>'3.6' bar==2.0; sys_platform=='win32'" -> ["foo==1.0; python_version>'3.6'", "bar==2.0; sys_platform=='win32'"]
    """  # noqa: E501
    packages: list[str] = []
    current_package: list[str] = []
    in_environment_marker = False

    for part in package.split():
        if part in ["-e", "--editable", "@"]:
            current_package.append(part)
        elif current_package and current_package[-1] in [
            "-e",
            "--editable",
            "@",
        ]:
            current_package.append(part)
        elif part.endswith(";"):
            if current_package:
                packages.append(" ".join(current_package))
                current_package = []
            in_environment_marker = True
            current_package.append(part)
        elif in_environment_marker:
            current_package.append(part)
            if part.endswith("'") or part.endswith('"'):
                in_environment_marker = False
                packages.append(" ".join(current_package))
                current_package = []
        else:
            if current_package:
                packages.append(" ".join(current_package))
            current_package = [part]

    if current_package:
        packages.append(" ".join(current_package))

    return [pkg.strip() for pkg in packages]


@dataclasses.dataclass
class PackageRequirement:
    """A package requirement with name and optional extras."""

    name: str
    extras: set[str] = dataclasses.field(default_factory=set)

    @classmethod
    def parse(cls, requirement: str) -> PackageRequirement:
        """Parse a package requirement string into name and extras."""
        match = re.match(r"^([^\[\]]+)(?:\[([^\[\]]+)\])?$", requirement)
        if not match:
            return cls(name=requirement)
        name = match.group(1)
        extras = set(match.group(2).split(",")) if match.group(2) else set()
        return cls(name=name, extras=extras)

    def __str__(self) -> str:
        """Convert back to a package requirement string."""
        if not self.extras:
            return self.name
        return f"{self.name}[{','.join(sorted(self.extras))}]"
