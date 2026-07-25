#!/usr/bin/env python3
"""List integration test files containing pytest-collected ``real_db`` items."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


class _RealDbCollector:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.targets: set[str] = set()
        self.errors: list[str] = []

    @pytest.hookimpl
    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.errors.append(str(report.longrepr))

    @pytest.hookimpl
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        for item in session.items:
            if item.get_closest_marker("real_db") is None:
                continue
            path = Path(str(item.path)).resolve()
            try:
                relative = path.relative_to(self.root).as_posix()
            except ValueError:
                self.errors.append(f"collected real_db item outside repository: {path}")
                continue
            relative_path = Path(relative)
            if (
                relative_path.parts[:2] != ("tests", "integration")
                or relative_path.name[:5] != "test_"
                or relative_path.suffix != ".py"
            ):
                self.errors.append(f"real_db item is outside the integration test surface: {relative}")
                continue
            self.targets.add(relative)


def discover(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    integration_dir = root / "tests" / "integration"
    if not integration_dir.is_dir():
        raise RuntimeError(f"integration test directory is missing: {integration_dir}")

    collector = _RealDbCollector(root)
    previous_cwd = Path.cwd()
    isolated_environment = {
        "PYTEST_ADDOPTS": None,
        "PYTEST_PLUGINS": None,
        "PYTHONPATH": None,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    previous_environment = {
        name: os.environ.get(name) for name in isolated_environment
    }
    try:
        for name, value in isolated_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        os.chdir(root)
        status = pytest.main(
            [
                "--collect-only",
                "--strict-markers",
                "-p",
                "no:terminal",
                "-p",
                "no:cacheprovider",
                "-p",
                "pytest_cov.plugin",
                "-p",
                "pytest_asyncio.plugin",
                "-p",
                "anyio.pytest_plugin",
                "-o",
                "addopts=",
                "tests/integration",
            ],
            plugins=[collector],
        )
    finally:
        os.chdir(previous_cwd)
        for name, value in previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    if status != pytest.ExitCode.OK or collector.errors:
        details = "\n".join(collector.errors) or f"pytest collection exited with status {int(status)}"
        raise RuntimeError(details)
    return tuple(sorted(collector.targets))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        targets = discover(args.root)
    except RuntimeError as exc:
        print(f"discover-real-db-targets: {exc}", file=sys.stderr)
        return 2
    for target in targets:
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
