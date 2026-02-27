#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
BREAKING_SUBJECT_RE = re.compile(r"^[a-zA-Z]+(?:\([^)]*\))?!:")


@dataclass(frozen=True)
class CommitRow:
    sha: str
    subject: str
    body: str


def _run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"git_exit_{completed.returncode}"
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def _latest_semver_tag() -> tuple[str, tuple[int, int, int]] | None:
    out = _run_git(["tag", "--list", "--sort=-version:refname"])
    for raw in out.splitlines():
        token = raw.strip()
        if not token:
            continue
        match = SEMVER_RE.match(token)
        if not match:
            continue
        return (token, (int(match.group(1)), int(match.group(2)), int(match.group(3))))
    return None


def _commits_since(tag: str | None) -> list[CommitRow]:
    range_spec = "HEAD" if not tag else f"{tag}..HEAD"
    fmt = "%H%x1f%s%x1f%b%x1e"
    out = _run_git(["log", "--format=" + fmt, range_spec])
    rows: list[CommitRow] = []
    for block in out.split("\x1e"):
        item = block.strip()
        if not item:
            continue
        parts = item.split("\x1f")
        if len(parts) < 3:
            continue
        sha = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip()
        if "[skip release]" in subject.lower() or "[skip release]" in body.lower():
            continue
        rows.append(CommitRow(sha=sha, subject=subject, body=body))
    return rows


def _detect_bump(commits: list[CommitRow]) -> str:
    if not commits:
        return "none"
    saw_minor = False
    for row in commits:
        subject = row.subject.strip()
        body = row.body.strip()
        if BREAKING_SUBJECT_RE.match(subject) or "BREAKING CHANGE" in body:
            return "major"
        if subject.startswith("feat:") or subject.startswith("feat("):
            saw_minor = True
    return "minor" if saw_minor else "patch"


def _bump(version: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    if bump == "patch":
        return (major, minor, patch + 1)
    return (major, minor, patch)


def _replace_pyproject_version(pyproject: Path, next_version: tuple[int, int, int]) -> None:
    raw = pyproject.read_text(encoding="utf-8")
    next_token = f'{next_version[0]}.{next_version[1]}.{next_version[2]}'
    replaced, count = re.subn(
        r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$',
        f'version = "{next_token}"',
        raw,
        count=1,
    )
    if count != 1:
        raise RuntimeError("failed_to_update_pyproject_version")
    pyproject.write_text(replaced, encoding="utf-8")


def _emit_output(path: Path | None, payload: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as fh:
        for key, value in payload.items():
            fh.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute and optionally apply next SemVer version.")
    parser.add_argument("--pyproject", default="pyproject.toml")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--github-output", default="")
    args = parser.parse_args()

    pyproject = Path(args.pyproject).resolve()
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject_not_found:{pyproject}")

    latest = _latest_semver_tag()
    base_version = latest[1] if latest is not None else (0, 1, 0)
    latest_tag = latest[0] if latest is not None else ""
    commits = _commits_since(latest_tag or None)
    bump = _detect_bump(commits)
    next_version = _bump(base_version, bump)

    has_changes = bump != "none"
    if args.apply and has_changes:
        _replace_pyproject_version(pyproject, next_version)

    payload = {
        "latest_tag": latest_tag,
        "base_version": f"{base_version[0]}.{base_version[1]}.{base_version[2]}",
        "next_version": f"{next_version[0]}.{next_version[1]}.{next_version[2]}",
        "bump": bump,
        "has_changes": "true" if has_changes else "false",
        "commit_count": str(len(commits)),
    }
    _emit_output(Path(args.github_output).resolve() if args.github_output else None, payload)
    for key, value in payload.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error={exc}", file=sys.stderr)
        raise
