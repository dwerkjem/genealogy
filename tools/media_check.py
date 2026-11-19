#!/usr/bin/env python3
"""Check files under media/ against the naming convention and list the inbox.

Convention (see README.md):
    media/<Surname>/<Date>_<Type>_<Surname>-<Given>[_<Place>][_<n>].<ext>
    Date  = YYYY, YYYY-MM, YYYY-MM-DD, or "undated"
    Type  = one of TYPES below
Example: media/Smith/1921_Census_Smith-William_Toronto-ON.jpg

Usage: media_check.py [media]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TYPES = {
    "Birth", "Baptism", "Marriage", "Divorce", "Death", "Burial", "Obituary",
    "Census", "Military", "Immigration", "Naturalization", "Passenger",
    "Probate", "Will", "Land", "Tax", "Directory", "Newspaper", "Church",
    "Photo", "Letter", "DNA", "Other",
}
NAME_RE = re.compile(
    r"^(?P<date>\d{4}(-\d{2}(-\d{2})?)?|undated)"
    r"_(?P<type>[A-Za-z]+)"
    r"_(?P<surname>[A-Za-z'\-]+?)-(?P<given>[A-Za-z'\-]+)"
    r"(_[A-Za-z0-9'\-]+)*"
    r"\.(?P<ext>[a-z0-9]+)$"
)
EXTS = {"jpg", "jpeg", "png", "tif", "tiff", "pdf", "gif", "webp", "heic", "txt", "md", "mp3", "mp4"}


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "media")
    if not root.is_dir():
        print(f"{root}/ does not exist")
        return 1
    inbox, bad = [], []
    for fp in sorted(root.rglob("*")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        rel = fp.relative_to(root)
        if rel.parts[0] == "_inbox":
            inbox.append(rel)
            continue
        problems = []
        if len(rel.parts) != 2:
            problems.append("should be exactly media/<Surname>/<file>")
        m = NAME_RE.match(fp.name)
        if not m:
            problems.append("name doesn't match <Date>_<Type>_<Surname>-<Given>[_<Place>].<ext>")
        else:
            if m["type"] not in TYPES:
                problems.append(f"unknown type '{m['type']}'")
            if m["ext"] not in EXTS:
                problems.append(f"unexpected extension .{m['ext']}")
        if problems:
            bad.append((rel, problems))

    print(f"## Inbox ({len(inbox)} to file)")
    for r in inbox:
        print(f"- {r}")
    print(f"\n## Naming problems ({len(bad)})")
    for r, probs in bad:
        print(f"- {r}: {'; '.join(probs)}")
    if not inbox and not bad:
        print("\nAll media filed and named correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
