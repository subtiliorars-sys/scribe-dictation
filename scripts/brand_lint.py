#!/usr/bin/env python3
"""brand-lint — BLOCKING pre-commit hook (ecosystem git-guards convention).

Ported from Cairn's/.githooks/pre-push.d/20-brand-lint (bash) to a Python
script so it plugs into scribe-dictation's `pre-commit` framework config
(.pre-commit-config.yaml) as a local hook instead of a bash .githooks/
dispatcher. Same behaviour: block a commit that introduces prohibited
brand / program-affiliation strings on this repo's documentation surface.

Wordlist:    .githooks/brand-wordlist.txt   (one pattern/line; '#' = comment)
             -> missing/empty => no-op.
Scan paths:  .githooks/brand-scan-paths     (one path/line; '#' = comment)
             -> missing => defaults to README.md/CONTRIBUTING.md/CHANGELOG.md.
Override:    ALLOW_BRAND_STRINGS=1 git commit ...   (or git commit --no-verify)

Invoked by pre-commit with the staged filenames as argv; only files that
fall under a configured scan path are checked.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / ".githooks"
WORDLIST = HOOKS_DIR / "brand-wordlist.txt"
SCAN_PATHS_FILE = HOOKS_DIR / "brand-scan-paths"
DEFAULT_SCAN_PATHS = ("README.md", "CONTRIBUTING.md", "CHANGELOG.md")


def load_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def in_scan_paths(file_path: str, scan_paths: tuple[str, ...]) -> bool:
    p = Path(file_path.replace("\\", "/"))
    for sp in scan_paths:
        sp_norm = sp.rstrip("/")
        if str(p) == sp_norm or str(p).startswith(sp_norm + "/"):
            return True
    return False


def main(argv: list[str]) -> int:
    if os.environ.get("ALLOW_BRAND_STRINGS") == "1":
        return 0

    patterns = load_lines(WORDLIST)
    if not patterns:
        return 0  # no wordlist => nothing to enforce

    scan_paths_cfg = load_lines(SCAN_PATHS_FILE)
    scan_paths = tuple(scan_paths_cfg) if scan_paths_cfg else DEFAULT_SCAN_PATHS

    files = [f for f in argv if in_scan_paths(f, scan_paths)]
    if not files:
        return 0

    hits: list[str] = []
    for pat in patterns:
        try:
            regex = re.compile(r"\b" + pat + r"\b", re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pat), re.IGNORECASE)
        for f in files:
            fp = REPO_ROOT / f
            if not fp.is_file():
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{f}:{lineno}: matched '{pat}': {line.strip()}")

    if hits:
        sys.stderr.write(
            "\n\U0001f6ab  COMMIT BLOCKED (brand-lint) — brand / program-affiliation "
            "strings found:\n\n"
        )
        sys.stderr.write("\n".join(hits) + "\n\n")
        sys.stderr.write(
            "Fix the copy, prune this repo's own brand from "
            ".githooks/brand-wordlist.txt if it's a false positive, or override "
            "deliberately: ALLOW_BRAND_STRINGS=1 git commit ...\n\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
