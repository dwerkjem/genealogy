#!/usr/bin/env python3
"""Block commits that would publish protected names.

Terms live in .private-terms at the repo root (git-ignored, one per line,
# comments allowed). A multi-word term like "John Smith" also matches
"Smith, John", "Smith-John", "john_smith", "JOHN  SMITH", etc.

  check_private.py            check staged paths + contents (pre-commit)
  check_private.py --msg F    check a commit message file (commit-msg)
  check_private.py --all      check every tracked file at HEAD (audit)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, check=True).stdout.strip())
TERMS_FILE = ROOT / ".private-terms"
SEP = r"[\W_]*"


def patterns() -> list[tuple[str, re.Pattern]]:
    if not TERMS_FILE.exists():
        print("warning: .private-terms missing — private-name check skipped", file=sys.stderr)
        return []
    pats = []
    for line in TERMS_FILE.read_text().splitlines():
        term = line.split("#", 1)[0].strip()
        if not term:
            continue
        words = [re.escape(w) for w in re.split(r"[\s,_\-]+", term) if w]
        alts = {SEP.join(words), SEP.join(reversed(words))}
        pats.append((term, re.compile("|".join(f"(?:{a})" for a in alts), re.IGNORECASE)))
    return pats


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True, cwd=ROOT).stdout


def scan(label: str, text: str, pats, hits: list[str]) -> None:
    for term, pat in pats:
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                hits.append(f"{label}:{i}: matches protected term '{term}'")
                break


def main() -> int:
    pats = patterns()
    if not pats:
        return 0
    hits: list[str] = []
    if len(sys.argv) == 3 and sys.argv[1] == "--msg":
        scan("commit message", Path(sys.argv[2]).read_text(errors="replace"), pats, hits)
    else:
        if "--all" in sys.argv:
            files = [f for f in git("ls-files", "-z").decode().split("\0") if f]
            show = lambda f: git("show", f"HEAD:{f}")  # noqa: E731
        else:
            files = [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
                     .decode().split("\0") if f]
            show = lambda f: git("show", f":{f}")  # noqa: E731
        for f in files:
            scan("path " + f, f, pats, hits)
            data = show(f)
            if b"\0" in data[:8000]:
                continue  # binary: path checked only
            scan(f, data.decode("utf-8", errors="replace"), pats, hits)
    if hits:
        print("BLOCKED — protected names would be published:", file=sys.stderr)
        for h in hits:
            print("  " + h, file=sys.stderr)
        print("Anonymize them (tag 'anonymous' in Gramps, then `make export`) or edit the text.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
