#!/usr/bin/env python3
"""Audit a Gramps XML snapshot: stats, data-quality problems, research gaps.

Usage: tree_report.py [gramps-db/full/family-tree.gramps] [--media-root media] [--brief]

Reads plain or gzipped Gramps XML. Stdlib only. Exit code is 0 even when
issues are found; this is a report, not a gate.
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

THIS_YEAR = date.today().year
LIVING_CUTOFF = 110  # no death + born within this many years => presumed living


def strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def load(path: Path) -> ET.Element:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    strip_ns(root)
    return root


def year_of(dateobj: ET.Element | None) -> tuple[int | None, str]:
    """Return (year, quality) from an event's date child. quality: exact/about/range/text/none."""
    if dateobj is None:
        return None, "none"
    for tag in ("dateval", "daterange", "datespan"):
        d = dateobj.find(tag)
        if d is not None:
            val = d.get("val") or d.get("start") or ""
            m = re.match(r"(\d{3,4})", val)
            q = d.get("type") or d.get("quality") or ("exact" if tag == "dateval" else "range")
            return (int(m.group(1)) if m and int(m.group(1)) > 0 else None), q
    if dateobj.find("datestr") is not None:
        return None, "text"
    return None, "none"


@dataclass
class Event:
    handle: str
    type: str
    year: int | None
    quality: str
    place: str | None
    citations: list[str]


@dataclass
class Person:
    handle: str
    id: str
    gender: str
    given: str
    surname: str
    prefix_only: bool
    events: list[tuple[str, str]] = field(default_factory=list)  # (event handle, role)
    citations: list[str] = field(default_factory=list)
    childof: list[str] = field(default_factory=list)
    parentin: list[str] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    media: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        name = f"{self.given} {self.surname}".strip() or "(no name)"
        return f"{name} [{self.id}]"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def parse(root: ET.Element):
    events: dict[str, Event] = {}
    for e in root.iterfind("events/event"):
        y, q = year_of(e)
        pl = e.find("place")
        events[e.get("handle")] = Event(
            e.get("handle"),
            (e.findtext("type") or "").strip(),
            y,
            q,
            pl.get("hlink") if pl is not None else None,
            [c.get("hlink") for c in e.findall("citationref")],
        )

    people: dict[str, Person] = {}
    for p in root.iterfind("people/person"):
        name = p.find("name")
        given = surname = ""
        prefix_only = False
        if name is not None:
            given = (name.findtext("first") or "").strip()
            sns = name.findall("surname")
            surname = " ".join((s.text or "").strip() for s in sns).strip()
            if not surname and any(s.get("prefix") for s in sns):
                prefix_only = True
                surname = " ".join(s.get("prefix", "") for s in sns).strip()
        per = Person(
            p.get("handle"), p.get("id"), (p.findtext("gender") or "U").strip(),
            given, surname, prefix_only,
        )
        per.events = [(r.get("hlink"), r.get("role", "Primary")) for r in p.findall("eventref")]
        per.citations = [c.get("hlink") for c in p.findall("citationref")]
        per.childof = [c.get("hlink") for c in p.findall("childof")]
        per.parentin = [c.get("hlink") for c in p.findall("parentin")]
        per.media = [o.get("hlink") for o in p.findall("objref")]
        for a in p.findall("attribute"):
            per.attrs[a.get("type", "")] = a.get("value", "")
        people[per.handle] = per

    families = {}
    for f in root.iterfind("families/family"):
        fa, mo = f.find("father"), f.find("mother")
        families[f.get("handle")] = {
            "id": f.get("id"),
            "father": fa.get("hlink") if fa is not None else None,
            "mother": mo.get("hlink") if mo is not None else None,
            "children": [c.get("hlink") for c in f.findall("childref")],
            "events": [r.get("hlink") for r in f.findall("eventref")],
            "citations": [c.get("hlink") for c in f.findall("citationref")],
        }

    citations = {c.get("handle"): c for c in root.iterfind("citations/citation")}
    sources = {s.get("handle"): s for s in root.iterfind("sources/source")}
    media = {}
    for o in root.iterfind("objects/object"):
        fe = o.find("file")
        media[o.get("handle")] = {
            "id": o.get("id"),
            "src": fe.get("src") if fe is not None else "",
            "desc": fe.get("description", "") if fe is not None else "",
        }
    home_el = root.find("people")
    home = home_el.get("home") if home_el is not None else None
    return events, people, families, citations, sources, media, home


def vital(person: Person, events: dict[str, Event], kinds: tuple[str, ...]) -> Event | None:
    for h, role in person.events:
        ev = events.get(h)
        if ev and role == "Primary" and ev.type in kinds:
            return ev
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xml", nargs="?", default="gramps-db/full/family-tree.gramps")
    ap.add_argument("--media-root", default="media")
    ap.add_argument("--brief", action="store_true", help="counts only, no per-person listings")
    args = ap.parse_args()

    path = Path(args.xml)
    if not path.exists():
        print(f"No snapshot at {path}. Run `make export` first.", file=sys.stderr)
        return 1
    events, people, families, citations, sources, media, home = parse(load(path))

    def birth(p):
        return vital(p, events, ("Birth", "Baptism", "Christening"))

    def death(p):
        return vital(p, events, ("Death", "Burial", "Cremation"))

    issues: dict[str, list[str]] = defaultdict(list)

    # --- per-person checks
    for p in people.values():
        b, d = birth(p), death(p)
        by, dy = (b.year if b else None), (d.year if d else None)
        if p.prefix_only:
            issues["Surname typed into the prefix field"].append(p.label)
        elif not p.surname:
            issues["No surname"].append(p.label)
        if not b:
            issues["No birth/baptism event"].append(p.label)
        elif by is None:
            issues["Birth event has no usable date"].append(p.label)
        if by and dy and dy < by:
            issues["Death before birth"].append(f"{p.label}: b.{by} d.{dy}")
        if by and dy and dy - by > LIVING_CUTOFF:
            issues[f"Lifespan over {LIVING_CUTOFF} years"].append(f"{p.label}: b.{by} d.{dy}")
        if not p.childof:
            issues["No parents linked (research frontier)"].append(p.label)
        # Unsourced facts: primary events with no citation on the event
        for h, role in p.events:
            ev = events.get(h)
            if ev and role == "Primary" and not ev.citations:
                issues["Unsourced events"].append(f"{p.label}: {ev.type}" + (f" {ev.year}" if ev.year else ""))
        if not p.citations and not any(events.get(h) and events[h].citations for h, _ in p.events):
            issues["Person has no citations at all"].append(p.label)

    # --- parent/child age sanity
    for f in families.values():
        for ch in f["children"]:
            c = people.get(ch)
            cb = birth(c) if c else None
            if not cb or cb.year is None:
                continue
            for role in ("father", "mother"):
                par = people.get(f[role]) if f[role] else None
                if not par:
                    continue
                pb, pd = birth(par), death(par)
                if pb and pb.year:
                    age = cb.year - pb.year
                    if age < 13:
                        issues["Parent under 13 at child's birth"].append(f"{par.label} -> {c.label} (age {age})")
                    elif role == "mother" and age > 50:
                        issues["Mother over 50 at child's birth"].append(f"{par.label} -> {c.label} (age {age})")
                    elif role == "father" and age > 75:
                        issues["Father over 75 at child's birth"].append(f"{par.label} -> {c.label} (age {age})")
                if pd and pd.year:
                    slack = 1 if role == "father" else 0
                    if cb.year > pd.year + slack:
                        issues["Child born after parent's death"].append(
                            f"{par.label} d.{pd.year} -> {c.label} b.{cb.year}")

    # --- possible duplicates
    buckets = defaultdict(list)
    for p in people.values():
        b = birth(p)
        buckets[(norm(p.given.split()[0] if p.given else ""), norm(p.surname))].append((p, b.year if b else None))
    for (g, s), group in buckets.items():
        if len(group) < 2 or not g or not s:
            continue
        for i, (p1, y1) in enumerate(group):
            for p2, y2 in group[i + 1:]:
                if y1 is None or y2 is None or abs(y1 - y2) <= 2:
                    issues["Possible duplicates (same name, birth within 2 yrs)"].append(f"{p1.label} ~ {p2.label}")

    # --- media
    media_root = Path(args.media_root)
    referenced = set()
    for m in media.values():
        src = m["src"]
        fp = Path(src) if Path(src).is_absolute() else media_root / src
        referenced.add(fp.resolve())
        if Path(src).is_absolute():
            issues["Media with absolute path (should be relative to media/)"].append(f"{m['id']}: {src}")
        if not fp.exists():
            issues["Media file missing on disk"].append(f"{m['id']}: {src}")
    if media_root.is_dir():
        for fp in media_root.rglob("*"):
            if fp.is_file() and not fp.name.startswith(".") and "_inbox" not in fp.parts \
                    and fp.resolve() not in referenced:
                issues["Files in media/ not attached in Gramps"].append(str(fp))

    # --- living people (privacy)
    living = []
    for p in people.values():
        b, d = birth(p), death(p)
        if not d and (not b or not b.year or THIS_YEAR - b.year < LIVING_CUTOFF):
            living.append(p)

    # --- pedigree completeness from home person
    pedigree = []
    if home and home in people:
        gen = [home]
        for n in range(1, 11):
            nxt = []
            for h in gen:
                for fh in people[h].childof[:1]:
                    fam = families.get(fh, {})
                    nxt += [x for x in (fam.get("father"), fam.get("mother")) if x]
            if n > 1:
                pedigree.append((n, len(gen), 2 ** (n - 1)))
            if not nxt:
                break
            gen = nxt

    # --- output
    print(f"# Tree report — {path} ({date.today().isoformat()})\n")
    print(f"People {len(people)} · Families {len(families)} · Events {len(events)} · "
          f"Sources {len(sources)} · Citations {len(citations)} · Media {len(media)}")
    print(f"Presumed living (privacy-sensitive): {len(living)}")
    if home in people:
        print(f"Home person: {people[home].label}")
    if pedigree:
        print("\n## Pedigree completeness (direct ancestors)")
        print("| Gen | Found | Possible | % |\n|---|---|---|---|")
        for n, found, possible in pedigree:
            print(f"| {n} | {found} | {possible} | {100 * found // possible}% |")
    print("\n## Issues")
    if not issues:
        print("None found.")
    for title, items in sorted(issues.items(), key=lambda kv: -len(kv[1])):
        print(f"\n### {title} ({len(items)})")
        if not args.brief:
            for it in sorted(items)[:200]:
                print(f"- {it}")
            if len(items) > 200:
                print(f"- … {len(items) - 200} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
