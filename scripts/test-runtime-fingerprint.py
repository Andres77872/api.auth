#!/usr/bin/env python3
"""Print a deterministic fingerprint of the pinned test runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Callable, Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, canonicalize_version
from packaging.version import InvalidVersion, Version


ROOT = Path(__file__).resolve().parents[1]
ROOT_REQUIREMENTS_PATTERN = "requirements*.txt"
_INLINE_COMMENT = re.compile(r"\s+#.*$")
RUNTIME_TOOLING_EXCLUSIONS = frozenset({"pip", "setuptools", "wheel"})


class RuntimeFingerprintError(RuntimeError):
    """Raised when the installed dependency surface cannot be certified."""


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _validate_requirement_file(root: Path, candidate: Path) -> Path:
    """Return a safe absolute requirement path below root."""

    lexical_path = Path(os.path.abspath(candidate))
    try:
        relative_path = lexical_path.relative_to(root)
    except ValueError as exc:
        raise RuntimeFingerprintError(
            f"requirement include escapes repository root: {candidate}"
        ) from exc

    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeFingerprintError(
                "symlinked requirement input is not allowed: "
                + relative_path.as_posix()
            )

    if not lexical_path.exists():
        raise RuntimeFingerprintError(
            f"requirement input does not exist: {relative_path.as_posix()}"
        )
    if not lexical_path.is_file():
        raise RuntimeFingerprintError(
            f"requirement input is not a regular file: {relative_path.as_posix()}"
        )
    return lexical_path


def _strip_comment(raw_line: str) -> str:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return ""
    return _INLINE_COMMENT.sub("", line).strip()


def _include_target(line: str, source: str) -> str | None:
    """Parse a supported pip requirement-file include directive."""

    if line.startswith("--requirement="):
        target = line.removeprefix("--requirement=").strip()
        if not target:
            raise RuntimeFingerprintError(f"{source}: empty requirement include")
        return target

    if line.startswith("-r") and not line.startswith("-r "):
        target = line[2:].strip()
        if not target:
            raise RuntimeFingerprintError(f"{source}: empty requirement include")
        return target

    try:
        tokens = shlex.split(line, comments=False, posix=True)
    except ValueError as exc:
        raise RuntimeFingerprintError(f"{source}: invalid requirement syntax: {exc}") from exc

    if tokens and tokens[0] in {"-r", "--requirement"}:
        if len(tokens) != 2:
            raise RuntimeFingerprintError(
                f"{source}: requirement include must name exactly one file"
            )
        return tokens[1]
    return None


def collect_pinned_requirements(root: Path = ROOT) -> tuple[tuple[str, str], ...]:
    """Collect active exact pins from root requirement files and their includes."""

    root = root.resolve()
    if not root.is_dir():
        raise RuntimeFingerprintError(f"repository root is not a directory: {root}")

    root_inputs = sorted(
        root.glob(ROOT_REQUIREMENTS_PATTERN), key=lambda path: path.name
    )
    if not root_inputs:
        raise RuntimeFingerprintError(
            f"no root requirement files match {ROOT_REQUIREMENTS_PATTERN!r}"
        )

    pins: dict[str, tuple[Version, str]] = {}
    visited: set[Path] = set()
    active_stack: list[Path] = []

    def visit(candidate: Path) -> None:
        path = _validate_requirement_file(root, candidate)
        if path in active_stack:
            cycle = active_stack[active_stack.index(path) :] + [path]
            rendered = " -> ".join(_display_path(root, item) for item in cycle)
            raise RuntimeFingerprintError(f"cyclic requirement include: {rendered}")
        if path in visited:
            return

        active_stack.append(path)
        try:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError) as exc:
                raise RuntimeFingerprintError(
                    f"cannot read requirement input {_display_path(root, path)}: {exc}"
                ) from exc

            for line_number, raw_line in enumerate(lines, start=1):
                line = _strip_comment(raw_line)
                if not line:
                    continue
                source = f"{_display_path(root, path)}:{line_number}"

                include = _include_target(line, source)
                if include is not None:
                    visit(path.parent / include)
                    continue

                if line.startswith(("-e ", "--editable ", "--editable=")):
                    raise RuntimeFingerprintError(
                        f"{source}: editable requirements are not supported"
                    )
                if line.startswith("-"):
                    raise RuntimeFingerprintError(
                        f"{source}: unsupported requirement-file option: {line}"
                    )

                try:
                    requirement = Requirement(line)
                except InvalidRequirement as exc:
                    raise RuntimeFingerprintError(
                        f"{source}: unsupported or invalid requirement: {line}"
                    ) from exc

                if requirement.url is not None:
                    raise RuntimeFingerprintError(
                        f"{source}: URL requirements are not supported"
                    )
                if requirement.marker is not None and not requirement.marker.evaluate():
                    continue

                specifiers = tuple(requirement.specifier)
                if (
                    len(specifiers) != 1
                    or specifiers[0].operator != "=="
                    or "*" in specifiers[0].version
                ):
                    raise RuntimeFingerprintError(
                        f"{source}: active requirement must use one exact == pin: {line}"
                    )

                try:
                    pinned_version = Version(specifiers[0].version)
                except InvalidVersion as exc:
                    raise RuntimeFingerprintError(
                        f"{source}: invalid pinned version: {specifiers[0].version}"
                    ) from exc

                name = canonicalize_name(requirement.name)
                canonical_version = canonicalize_version(pinned_version)
                previous = pins.get(name)
                if previous is not None and previous[0] != pinned_version:
                    raise RuntimeFingerprintError(
                        f"{source}: conflicting pins for {name}: "
                        f"{previous[1]} and {canonical_version}"
                    )
                pins[name] = (pinned_version, canonical_version)
        finally:
            active_stack.pop()
        visited.add(path)

    for root_input in root_inputs:
        visit(root_input)

    if not pins:
        raise RuntimeFingerprintError("no active pinned package requirements found")
    return tuple((name, pins[name][1]) for name in sorted(pins))


def resolve_installed_requirements(
    root: Path = ROOT,
    version_lookup: Callable[[str], str] | None = None,
) -> tuple[str, ...]:
    """Validate every pin and return canonical installed package/version pairs."""

    lookup = version_lookup or importlib.metadata.version
    pairs: list[str] = []
    for name, pinned_version_text in collect_pinned_requirements(root):
        pinned_version = Version(pinned_version_text)
        try:
            installed_version_text = lookup(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeFingerprintError(
                f"required distribution is not installed: {name}=={pinned_version_text}"
            ) from exc
        except Exception as exc:
            raise RuntimeFingerprintError(
                f"cannot inspect installed distribution {name}: {exc}"
            ) from exc

        try:
            installed_version = Version(installed_version_text)
        except InvalidVersion as exc:
            raise RuntimeFingerprintError(
                f"installed distribution has an invalid version: "
                f"{name}=={installed_version_text}"
            ) from exc
        if installed_version != pinned_version:
            raise RuntimeFingerprintError(
                f"installed distribution version mismatch for {name}: "
                f"required {pinned_version}, installed {installed_version}"
            )
        pairs.append(f"{name}=={canonicalize_version(installed_version)}")
    return tuple(pairs)


def resolve_runtime_environment(
    root: Path = ROOT,
    version_lookup: Callable[[str], str] | None = None,
    distributions: Iterable[importlib.metadata.Distribution] | None = None,
) -> tuple[str, ...]:
    """Return the complete installed, exactly pinned non-tooling environment."""

    pinned_pairs = resolve_installed_requirements(root, version_lookup)
    pinned = dict(pair.split("==", 1) for pair in pinned_pairs)
    installed: dict[str, str] = {}
    distribution_iter = (
        importlib.metadata.distributions() if distributions is None else distributions
    )

    for distribution in distribution_iter:
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            raise RuntimeFingerprintError(
                "installed distribution is missing its canonical Name metadata"
            )
        name = canonicalize_name(raw_name)
        if name in RUNTIME_TOOLING_EXCLUSIONS:
            continue
        try:
            version = canonicalize_version(Version(distribution.version))
        except InvalidVersion as exc:
            raise RuntimeFingerprintError(
                f"installed distribution has an invalid version: "
                f"{name}=={distribution.version}"
            ) from exc

        previous = installed.get(name)
        if previous is not None and previous != version:
            raise RuntimeFingerprintError(
                f"conflicting installed distributions for {name}: "
                f"{previous} and {version}"
            )
        installed[name] = version

    for name, pinned_version in pinned.items():
        installed_version = installed.get(name)
        if installed_version is None:
            raise RuntimeFingerprintError(
                f"pinned distribution is absent from installed metadata: "
                f"{name}=={pinned_version}"
            )
        if installed_version != pinned_version:
            raise RuntimeFingerprintError(
                f"installed metadata mismatch for {name}: "
                f"required {pinned_version}, installed {installed_version}"
            )

    unpinned = sorted(set(installed) - set(pinned))
    if unpinned:
        rendered = ", ".join(
            f"{name}=={installed[name]}" for name in unpinned
        )
        raise RuntimeFingerprintError(
            f"installed non-tooling distributions are not exactly pinned: {rendered}"
        )

    return tuple(f"{name}=={installed[name]}" for name in sorted(installed))


def runtime_fingerprint(
    root: Path = ROOT,
    version_lookup: Callable[[str], str] | None = None,
    distributions: Iterable[importlib.metadata.Distribution] | None = None,
) -> str:
    """Return SHA-256 over the complete pinned installed environment."""

    pairs = resolve_runtime_environment(root, version_lookup, distributions)
    canonical_payload = "".join(f"{pair}\n" for pair in pairs).encode("utf-8")
    return hashlib.sha256(canonical_payload).hexdigest()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate exact dependency pins and print their runtime SHA-256."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root containing requirements*.txt files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        fingerprint = runtime_fingerprint(args.root)
    except RuntimeFingerprintError as exc:
        print(f"test-runtime-fingerprint: {exc}", file=sys.stderr)
        return 2
    print(fingerprint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
