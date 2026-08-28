#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
from typing import Iterable


FORBIDDEN_PATH_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "recordings",
    ".idea",
    ".vscode",
    "superpowers",
}
FORBIDDEN_EXACT_PATHS = {
    Path("config/remembered-devices.json"),
    Path("config/emonio-viewer.local.toml"),
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".zip", ".log", ".sqlite", ".sqlite3", ".swp", ".swo"}
PRIVATE_IPV4 = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
FIELD_DEVICE_PATTERN = re.compile(r"\bemonio-[0-9a-f]{6,}\b")
SECRET_PATTERNS = (
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key material"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]+"), "GitHub token"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE), "HTTP bearer authorization"),
)


def _negative_regression_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("assert ") and " not in " in stripped


def _path_findings(relative: Path) -> list[str]:
    findings: list[str] = []
    if relative in FORBIDDEN_EXACT_PATHS:
        findings.append(f"forbidden path: {relative.as_posix()}")
    if any(part in FORBIDDEN_PATH_PARTS for part in relative.parts):
        findings.append(f"forbidden path: {relative.as_posix()}")
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        findings.append(f"forbidden path suffix: {relative.as_posix()}")
    if relative.name in {".DS_Store", "Thumbs.db"}:
        findings.append(f"forbidden path: {relative.as_posix()}")
    if relative.name.startswith(".env") and relative.name != ".env.example":
        findings.append(f"forbidden environment file: {relative.as_posix()}")
    return findings


def _content_findings(relative: Path, data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _negative_regression_line(line):
            continue
        if PRIVATE_IPV4.search(line):
            findings.append(f"private IPv4 address: {relative.as_posix()}:{line_number}")
        if FIELD_DEVICE_PATTERN.search(line):
            findings.append(f"field device identity: {relative.as_posix()}:{line_number}")
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(f"{label}: {relative.as_posix()}:{line_number}")
    return findings


def scan_files(root: Path, paths: Iterable[Path]) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    for relative in sorted(paths, key=lambda path: path.as_posix()):
        findings.extend(_path_findings(relative))
        path = root / relative
        if path.is_file():
            findings.extend(_content_findings(relative, path.read_bytes()))
    return findings


def _staged_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def scan_staged(root: Path) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    for relative in _staged_paths(root):
        findings.extend(_path_findings(relative))
        blob = subprocess.run(
            ["git", "show", f":{relative.as_posix()}"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        findings.extend(_content_findings(relative, blob))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan ARI Emonio Viewer publication content")
    parser.add_argument("--staged", action="store_true", help="scan exact staged Git blobs")
    parser.add_argument("--working-tree", action="store_true", help="scan current public working-tree files")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]

    if args.staged == args.working_tree:
        parser.error("select exactly one of --staged or --working-tree")

    if args.staged:
        findings = scan_staged(root)
    else:
        paths = [path.relative_to(root) for path in root.rglob("*") if path.is_file()]
        findings = scan_files(root, paths)

    if findings:
        print("ARI Emonio Publication Gate: FAIL")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("ARI Emonio Publication Gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
