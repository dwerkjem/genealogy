#!/usr/bin/env python3
"""gt — read and edit the Gramps tree from the command line.

Uses Gramps' own database API (the same layer the GUI uses), so edits are
real Gramps objects inside transactions. Every write:
  1. refuses if the tree is open in Gramps (lock file present),
  2. copies the SQLite DB to gramps-db/backups/ first,
  3. re-exports tree/ afterwards (skip with --no-export) so `git diff tree/`
     shows exactly what changed.

Objects are addressed by Gramps ID: I0001 person, F0001 family, E0001 event,
S0001 source, C0001 citation, P0001 place, O0001 media, N0001 note.
Dates use Gramps syntax: "1890", "abt 1890", "1890-05-03", "bef 1900",
"between 1890 and 1895", "from 1914 to 1918".
Places are comma-separated, most specific first: "Toronto, Ontario, Canada"
(the hierarchy is created/reused automatically).

Run `gt.py <command> -h` for details. Usually invoked as `make gt ARGS="..."`
or `uv run python tools/gt.py ...`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Gtk (pulled in by Gramps) prints a harmless "xapp-gtk3-module" warning from C
# code. Send the C-level stderr fd to /dev/null but keep Python's sys.stderr on
# the real terminal, so our own errors and tracebacks still show.
_stderr = os.dup(2)
os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
sys.stderr = os.fdopen(_stderr, "w", buffering=1)
try:
    from gramps.gen.db import DbTxn
    from gramps.gen.db.utils import (clear_lock_file, lookup_family_tree,
                                     open_database, write_lock_file)
    from gramps.gen.datehandler import displayer as date_displayer
    from gramps.gen.datehandler import parser as date_parser
    from gramps.gen.display.name import displayer as name_displayer
    from gramps.gen.display.place import displayer as place_displayer
    from gramps.gen.lib import (Attribute, AttributeType, ChildRef, Citation,
                                Date, Event, EventRef, EventRoleType,
                                EventType, Family, FamilyRelType, Media,
                                MediaRef, Name, Note, NoteType, Person, Place,
                                PlaceName, PlaceRef, PlaceType, RepoRef,
                                Repository, RepositoryType, Source,
                                SrcAttribute, StyledText, Surname, Tag)
    from gramps.gen.mime import get_type as mime_type
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Can't import Gramps ({exc}).\nThe venv must use system Python with "
             "system site-packages: run `make venv`.")

ROOT = Path(__file__).resolve().parent.parent
MEDIA_ROOT = ROOT / "media"
BACKUPS = ROOT / "gramps-db" / "backups"
KEEP_BACKUPS = 30
DEFAULT_TREE = os.environ.get("GRAMPS_TREE", "Family Tree")

GENDERS = {"M": Person.MALE, "F": Person.FEMALE, "U": Person.UNKNOWN}
CONFIDENCE = {"very-low": Citation.CONF_VERY_LOW, "low": Citation.CONF_LOW,
              "normal": Citation.CONF_NORMAL, "high": Citation.CONF_HIGH,
              "very-high": Citation.CONF_VERY_HIGH}
CONF_NAMES = {v: k for k, v in CONFIDENCE.items()}


class GtError(Exception):
    pass


# ---------------------------------------------------------------- db access

@contextmanager
def tree(name: str, write: bool):
    data = lookup_family_tree(name)
    if not data:
        raise GtError(f"No Gramps family tree named {name!r}.")
    dbpath, locked, locked_by, _backend = data
    if locked:
        raise GtError(f"Tree is open in Gramps ({locked_by}). Close Gramps first.")
    if write:
        backup(Path(dbpath))
    db = open_database(name)
    if db is None:
        raise GtError(f"Could not open {name!r}.")
    if write:
        write_lock_file(dbpath)  # stop the GUI opening it mid-edit
    try:
        yield db
    finally:
        db.close()
        if write:
            clear_lock_file(dbpath)


def backup(dbpath: Path) -> None:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    src = dbpath / "sqlite.db"
    dst = BACKUPS / f"pre-edit-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    shutil.copy2(src, dst)
    old = sorted(BACKUPS.glob("pre-edit-*.db"))[:-KEEP_BACKUPS]
    for f in old:
        f.unlink()


# ---------------------------------------------------------------- lookups

def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def get(db, gid: str):
    """Return (kind, object) for any Gramps ID."""
    getters = {"I": ("person", db.get_person_from_gramps_id),
               "F": ("family", db.get_family_from_gramps_id),
               "E": ("event", db.get_event_from_gramps_id),
               "S": ("source", db.get_source_from_gramps_id),
               "C": ("citation", db.get_citation_from_gramps_id),
               "P": ("place", db.get_place_from_gramps_id),
               "O": ("media", db.get_media_from_gramps_id),
               "N": ("note", db.get_note_from_gramps_id),
               "R": ("repository", db.get_repository_from_gramps_id)}
    gid = gid.strip().upper()
    if gid[:1] not in getters:
        raise GtError(f"Unrecognised ID {gid!r}.")
    kind, fn = getters[gid[:1]]
    obj = fn(gid)
    if obj is None:
        raise GtError(f"No {kind} with ID {gid}.")
    return kind, obj


def person(db, gid: str) -> Person:
    kind, obj = get(db, gid)
    if kind != "person":
        raise GtError(f"{gid} is a {kind}, expected a person.")
    return obj


def commit(db, kind: str, obj, trans) -> None:
    getattr(db, f"commit_{kind}")(obj, trans)


def parse_date(text: str | None) -> Date | None:
    if not text:
        return None
    d = date_parser.parse(text)
    if d.get_modifier() == Date.MOD_TEXTONLY:
        raise GtError(f"Gramps can't parse date {text!r} (stored text-only dates break sorting/checks).")
    return d


def year_str(db, p: Person, birth: bool) -> str:
    ref = p.get_birth_ref() if birth else p.get_death_ref()
    if not ref:
        return ""
    d = db.get_event_from_handle(ref.ref).get_date_object()
    return str(d.get_year()) if d.get_year() else ""


def label(db, p: Person) -> str:
    b, d = year_str(db, p, True), year_str(db, p, False)
    life = f" ({b}–{d})" if b or d else ""
    return f"{p.gramps_id} {name_displayer.display(p)}{life}"


def place_title(db, handle) -> str:
    return place_displayer.display(db, db.get_place_from_handle(handle)) if handle else ""


# ---------------------------------------------------------------- creators

def find_or_create_place(db, text: str, trans) -> Place:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        raise GtError("Empty place.")
    want = norm(", ".join(parts))
    for pl in db.iter_places():
        if norm(place_displayer.display(db, pl)) == want:
            return pl
    parent = None
    for i, name in enumerate(reversed(parts)):
        found = None
        for pl in db.iter_places():
            if norm(pl.get_name().get_value()) != norm(name):
                continue
            refs = pl.get_placeref_list()
            if (parent is None and not refs) or (parent and refs and refs[0].ref == parent.handle):
                found = pl
                break
        if not found:
            found = Place()
            pn = PlaceName()
            pn.set_value(name)
            found.set_name(pn)
            found.set_type(PlaceType(PlaceType.COUNTRY if i == 0 and len(parts) > 1 else PlaceType.UNKNOWN))
            if parent:
                pr = PlaceRef()
                pr.ref = parent.handle
                found.add_placeref(pr)
            db.add_place(found, trans)
        parent = found
    return parent


def make_event(db, etype: str, date: str | None, place: str | None, desc: str | None, trans) -> Event:
    ev = Event()
    et = EventType()
    et.set_from_xml_str(etype)  # standard types map; anything else becomes a custom type
    ev.set_type(et)
    if date:
        ev.set_date_object(parse_date(date))
    if place:
        ev.set_place_handle(find_or_create_place(db, place, trans).handle)
    if desc:
        ev.set_description(desc)
    db.add_event(ev, trans)
    return ev


def attach_event(p: Person, ev: Event, role=EventRoleType.PRIMARY) -> None:
    er = EventRef()
    er.ref = ev.handle
    er.set_role(EventRoleType(role))
    p.add_event_ref(er)
    t = ev.get_type()
    if role == EventRoleType.PRIMARY:
        if t == EventType.BIRTH and p.get_birth_ref() is None:
            p.set_birth_ref(er)
        elif t == EventType.DEATH and p.get_death_ref() is None:
            p.set_death_ref(er)


def fix_vitals(db, p: Person) -> None:
    """Recompute which event refs are the person's birth/death after edits."""
    p.set_birth_ref(None)
    p.set_death_ref(None)
    for er in p.get_event_ref_list():
        if int(er.get_role()) != EventRoleType.PRIMARY:
            continue
        t = db.get_event_from_handle(er.ref).get_type()
        if t == EventType.BIRTH and p.get_birth_ref() is None:
            p.set_birth_ref(er)
        elif t == EventType.DEATH and p.get_death_ref() is None:
            p.set_death_ref(er)


def find_family(db, father: Person | None, mother: Person | None) -> Family | None:
    anchor = father or mother
    for fh in anchor.get_family_handle_list():
        fam = db.get_family_from_handle(fh)
        if (fam.get_father_handle() == (father.handle if father else None)
                and fam.get_mother_handle() == (mother.handle if mother else None)):
            return fam
    return None


def find_or_create_family(db, father, mother, trans) -> tuple[Family, bool]:
    fam = find_family(db, father, mother)
    if fam:
        return fam, False
    fam = Family()
    fam.set_relationship(FamilyRelType(FamilyRelType.MARRIED if father and mother else FamilyRelType.UNKNOWN))
    if father:
        fam.set_father_handle(father.handle)
    if mother:
        fam.set_mother_handle(mother.handle)
    db.add_family(fam, trans)
    for par in (father, mother):
        if par:
            par.add_family_handle(fam.handle)
            db.commit_person(par, trans)
    return fam, True


# ---------------------------------------------------------------- commands (read)

def cmd_find(db, a):
    q = norm(a.query).split()
    hits = []
    for p in db.iter_people():
        names = [p.get_primary_name()] + p.get_alternate_names()
        hay = " ".join(norm(f"{n.get_first_name()} {n.get_surname()} {n.get_nick_name()} "
                            + " ".join(s.get_surname() for s in n.get_surname_list())) for n in names)
        hay += " " + p.gramps_id.lower()
        if all(t in hay for t in q):
            hits.append(p)
    for p in sorted(hits, key=lambda p: (name_displayer.sorted(p), p.gramps_id)):
        print(label(db, p))
    if not hits:
        print("No matches.")


def describe_event(db, ev: Event, role=None) -> str:
    bits = [str(ev.get_type())]
    if role is not None and int(role) != EventRoleType.PRIMARY:
        bits[0] += f" [{role}]"
    if not ev.get_date_object().is_empty():
        bits.append(date_displayer.display(ev.get_date_object()))
    if ev.get_place_handle():
        bits.append("@ " + place_title(db, ev.get_place_handle()))
    if ev.get_description():
        bits.append(f"“{ev.get_description()}”")
    cites = [db.get_citation_from_handle(h).gramps_id for h in ev.get_citation_list()]
    bits.append(f"[{', '.join(cites)}]" if cites else "[UNSOURCED]")
    return f"{ev.gramps_id} " + " ".join(bits)


def cmd_show(db, a):
    kind, obj = get(db, a.id)
    if kind == "person":
        show_person(db, obj)
    elif kind == "family":
        show_family(db, obj)
    elif kind == "citation":
        src = db.get_source_from_handle(obj.get_reference_handle())
        print(f"{obj.gramps_id} → {src.gramps_id} {src.get_title()}")
        print(f"  page: {obj.get_page()}\n  date: {date_displayer.display(obj.get_date_object())}"
              f"\n  confidence: {CONF_NAMES.get(obj.get_confidence_level())}")
        for at in obj.get_attribute_list():
            print(f"  {at.get_type()}: {at.get_value()}")
        for mr in obj.get_media_list():
            m = db.get_media_from_handle(mr.ref)
            print(f"  media {m.gramps_id}: {m.get_path()}")
        show_refs(db, obj.handle)
    elif kind == "source":
        print(f"{obj.gramps_id} {obj.get_title()}\n  author: {obj.get_author()}\n  pub: {obj.get_publication_info()}")
        show_refs(db, obj.handle)
    elif kind == "event":
        print(describe_event(db, obj))
        show_refs(db, obj.handle)
    elif kind == "place":
        print(f"{obj.gramps_id} {place_displayer.display(db, obj)} ({obj.get_type()})")
        show_refs(db, obj.handle)
    else:
        print(f"{obj.gramps_id} ({kind})")
        show_refs(db, obj.handle)


def show_refs(db, handle):
    for cls, h in db.find_backlink_handles(handle):
        kind = cls.lower()
        o = getattr(db, f"get_{kind}_from_handle")(h)
        lab = label(db, o) if kind == "person" else o.gramps_id
        print(f"  ← {cls} {lab}")


def show_person(db, p: Person):
    print(label(db, p) + f"  [{ {Person.MALE: 'M', Person.FEMALE: 'F'}.get(p.get_gender(), 'U') }]")
    for n in [p.get_primary_name()] + p.get_alternate_names():
        print(f"  name: {n.get_first_name()} / {n.get_surname()}  ({n.get_type()})")
    for at in p.get_attribute_list():
        print(f"  attr {at.get_type()}: {at.get_value()}")
    if p.get_tag_list():
        print("  tags: " + ", ".join(db.get_tag_from_handle(t).get_name() for t in p.get_tag_list()))
    print("  events:")
    for er in p.get_event_ref_list():
        print("    " + describe_event(db, db.get_event_from_handle(er.ref), er.get_role()))
    if p.get_citation_list():
        print("  person citations: " + ", ".join(db.get_citation_from_handle(h).gramps_id for h in p.get_citation_list()))
    for fh in p.get_parent_family_handle_list():
        fam = db.get_family_from_handle(fh)
        pars = [db.get_person_from_handle(h) for h in (fam.get_father_handle(), fam.get_mother_handle()) if h]
        print(f"  parents ({fam.gramps_id}): " + "; ".join(label(db, x) for x in pars))
    for fh in p.get_family_handle_list():
        fam = db.get_family_from_handle(fh)
        sp = fam.get_mother_handle() if fam.get_father_handle() == p.handle else fam.get_father_handle()
        print(f"  family {fam.gramps_id} with " + (label(db, db.get_person_from_handle(sp)) if sp else "(unknown)"))
        for cr in fam.get_child_ref_list():
            print("    child " + label(db, db.get_person_from_handle(cr.ref)))
    for nh in p.get_note_list():
        n = db.get_note_from_handle(nh)
        print(f"  note {n.gramps_id}: {n.get()[:200]}")
    for mr in p.get_media_list():
        m = db.get_media_from_handle(mr.ref)
        print(f"  media {m.gramps_id}: {m.get_path()}")


def show_family(db, fam: Family):
    print(f"{fam.gramps_id} ({fam.get_relationship()})")
    for role, h in (("father", fam.get_father_handle()), ("mother", fam.get_mother_handle())):
        if h:
            print(f"  {role}: {label(db, db.get_person_from_handle(h))}")
    for er in fam.get_event_ref_list():
        print("  " + describe_event(db, db.get_event_from_handle(er.ref)))
    for cr in fam.get_child_ref_list():
        print("  child: " + label(db, db.get_person_from_handle(cr.ref)))


def cmd_sources(db, a):
    for s in sorted(db.iter_sources(), key=lambda s: s.gramps_id):
        print(f"{s.gramps_id} {s.get_title()}")


# ---------------------------------------------------------------- commands (write)

def cmd_add_person(db, a, trans):
    p = Person()
    p.set_gender(GENDERS[a.gender.upper()])
    n = Name()
    n.set_first_name(a.given or "")
    sn = Surname()
    sn.set_surname(a.surname or "")
    sn.set_primary(True)
    n.add_surname(sn)
    p.set_primary_name(n)
    db.add_person(p, trans)
    for etype, spec in (("Birth", a.birth), ("Death", a.death)):
        if spec:
            date, _, place = spec.partition("@")
            attach_event(p, make_event(db, etype, date.strip() or None, place.strip() or None, None, trans))
    if a.fsid:
        p.add_attribute(make_attr("FSFTID", a.fsid))
    db.commit_person(p, trans)
    print(f"Added {label(db, p)}")
    return f"Add person {p.gramps_id}"


def make_attr(kind: str, value: str, cls=Attribute):
    at = cls()
    at.set_type(kind)  # known names map to built-in types, others become custom
    at.set_value(value)
    return at


def cmd_set_name(db, a, trans):
    p = person(db, a.id)
    n = p.get_primary_name()
    if a.given is not None:
        n.set_first_name(a.given)
    if a.surname is not None:
        sns = n.get_surname_list() or [Surname()]
        sns[0].set_surname(a.surname)
        sns[0].set_prefix(a.prefix or "")
        n.set_surname_list(sns)
    if a.gender:
        p.set_gender(GENDERS[a.gender.upper()])
    db.commit_person(p, trans)
    print(f"Updated {label(db, p)}")
    return f"Edit name {p.gramps_id}"


def cmd_add_name(db, a, trans):
    p = person(db, a.id)
    n = Name()
    n.set_first_name(a.given or p.get_primary_name().get_first_name())
    sn = Surname()
    sn.set_surname(a.surname)
    sn.set_primary(True)
    n.add_surname(sn)
    n.set_type(a.type)
    p.add_alternate_name(n)
    db.commit_person(p, trans)
    print(f"Added {a.type} name to {label(db, p)}")
    return f"Add alt name {p.gramps_id}"


def cmd_add_event(db, a, trans):
    kind, owner = get(db, a.id)
    if kind not in ("person", "family"):
        raise GtError("Events attach to a person (I…) or family (F…).")
    ev = make_event(db, a.type, a.date, a.place, a.desc, trans)
    if a.cite:
        _, c = get(db, a.cite)
        ev.add_citation(c.handle)
        db.commit_event(ev, trans)
    if kind == "person":
        attach_event(owner, ev)
        db.commit_person(owner, trans)
    else:
        er = EventRef()
        er.ref = ev.handle
        er.set_role(EventRoleType(EventRoleType.FAMILY))
        owner.add_event_ref(er)
        db.commit_family(owner, trans)
    for other in (a.also or "").split(","):
        if other.strip():
            o = person(db, other)
            attach_event(o, ev)
            db.commit_person(o, trans)
    print("Added " + describe_event(db, ev) + f" → {owner.gramps_id}")
    return f"Add {a.type} event to {owner.gramps_id}"


def cmd_edit_event(db, a, trans):
    _, ev = get(db, a.id)
    if a.date is not None:
        ev.set_date_object(parse_date(a.date) or Date())
    if a.place is not None:
        ev.set_place_handle(find_or_create_place(db, a.place, trans).handle if a.place else None)
    if a.desc is not None:
        ev.set_description(a.desc)
    db.commit_event(ev, trans)
    print("Updated " + describe_event(db, ev))
    return f"Edit event {ev.gramps_id}"


def cmd_add_source(db, a, trans):
    for s in db.iter_sources():
        if norm(s.get_title()) == norm(a.title):
            raise GtError(f"Source already exists: {s.gramps_id} {s.get_title()}")
    s = Source()
    s.set_title(a.title)
    s.set_author(a.author or "")
    s.set_publication_info(a.pubinfo or "")
    if a.repo:
        repo = next((r for r in db.iter_repositories() if norm(r.get_name()) == norm(a.repo)), None)
        if not repo:
            repo = Repository()
            repo.set_name(a.repo)
            repo.set_type(RepositoryType(RepositoryType.WEBSITE if a.repo_web else RepositoryType.ARCHIVE))
            db.add_repository(repo, trans)
        rr = RepoRef()
        rr.ref = repo.handle
        s.add_repo_reference(rr)
    db.add_source(s, trans)
    print(f"Added {s.gramps_id} {s.get_title()}")
    return f"Add source {s.gramps_id}"


def cmd_cite(db, a, trans):
    _, src = get(db, a.source)
    c = Citation()
    c.set_reference_handle(src.handle)
    c.set_page(a.page or "")
    c.set_confidence_level(CONFIDENCE[a.confidence])
    if a.date:
        c.set_date_object(parse_date(a.date))
    if a.url:
        c.add_attribute(make_attr("URL", a.url, SrcAttribute))
    c.add_attribute(make_attr("Accessed", datetime.now().strftime("%Y-%m-%d"), SrcAttribute))
    db.add_citation(c, trans)
    if a.media:
        m = find_or_create_media(db, a.media, trans)
        mr = MediaRef()
        mr.ref = m.handle
        c.add_media_reference(mr)
        db.commit_citation(c, trans)
    targets = []
    for tid in a.targets:
        kind, obj = get(db, tid)
        if not hasattr(obj, "add_citation"):
            raise GtError(f"Can't cite on a {kind}.")
        obj.add_citation(c.handle)
        commit(db, kind, obj, trans)
        targets.append(obj.gramps_id)
    print(f"Added {c.gramps_id} ({src.get_title()}: {c.get_page()}) → {', '.join(targets) or 'nothing'}")
    return f"Cite {c.gramps_id} on {', '.join(targets)}"


def find_or_create_media(db, path_str: str, trans) -> Media:
    fp = Path(path_str)
    if not fp.is_absolute():
        fp = (ROOT / fp) if (ROOT / fp).exists() else (MEDIA_ROOT / fp)
    fp = fp.resolve()
    if not fp.exists():
        raise GtError(f"File not found: {path_str}")
    try:
        rel = str(fp.relative_to(MEDIA_ROOT.resolve()))
    except ValueError:
        raise GtError(f"Media must live under {MEDIA_ROOT}/ — file it there first.")
    if rel.startswith("_inbox/"):
        raise GtError("File is still in media/_inbox/ — rename and file it before attaching.")
    for m in db.iter_media():
        if m.get_path() == rel:
            return m
    m = Media()
    m.set_path(rel)
    m.set_mime_type(mime_type(str(fp)))
    m.set_description(fp.stem)
    db.add_media(m, trans)
    return m


def cmd_attach_media(db, a, trans):
    kind, obj = get(db, a.id)
    m = find_or_create_media(db, a.path, trans)
    if a.desc:
        m.set_description(a.desc)
        db.commit_media(m, trans)
    mr = MediaRef()
    mr.ref = m.handle
    obj.add_media_reference(mr)
    commit(db, kind, obj, trans)
    print(f"Attached {m.gramps_id} {m.get_path()} → {obj.gramps_id}")
    return f"Attach media to {obj.gramps_id}"


def cmd_link_parents(db, a, trans):
    child = person(db, a.child)
    father = person(db, a.father) if a.father else None
    mother = person(db, a.mother) if a.mother else None
    if not (father or mother):
        raise GtError("Give --father and/or --mother.")
    fam, new = find_or_create_family(db, father, mother, trans)
    if any(cr.ref == child.handle for cr in fam.get_child_ref_list()):
        raise GtError(f"{child.gramps_id} is already a child in {fam.gramps_id}.")
    cr = ChildRef()
    cr.ref = child.handle
    fam.add_child_ref(cr)
    db.commit_family(fam, trans)
    child.add_parent_family_handle(fam.handle)
    db.commit_person(child, trans)
    print(f"{'Created' if new else 'Used'} family {fam.gramps_id}; {label(db, child)} is now a child of it.")
    return f"Link {child.gramps_id} to parents {fam.gramps_id}"


def cmd_link_spouse(db, a, trans):
    p1, p2 = person(db, a.id1), person(db, a.id2)
    father, mother = (p1, p2) if p1.get_gender() != Person.FEMALE else (p2, p1)
    fam, new = find_or_create_family(db, father, mother, trans)
    if not new:
        raise GtError(f"They already share family {fam.gramps_id}.")
    print(f"Created family {fam.gramps_id}: {label(db, father)} + {label(db, mother)}")
    return f"Add family {fam.gramps_id}"


def cmd_set_attr(db, a, trans):
    kind, obj = get(db, a.id)
    obj.set_attribute_list([at for at in obj.get_attribute_list() if str(at.get_type()) != a.type])
    obj.add_attribute(make_attr(a.type, a.value))
    commit(db, kind, obj, trans)
    print(f"{obj.gramps_id}: {a.type} = {a.value}")
    return f"Set {a.type} on {obj.gramps_id}"


def cmd_add_note(db, a, trans):
    kind, obj = get(db, a.id)
    n = Note()
    n.set_styledtext(StyledText(a.text))
    n.set_type(NoteType(NoteType.RESEARCH if a.research else NoteType.GENERAL))
    db.add_note(n, trans)
    obj.add_note(n.handle)
    commit(db, kind, obj, trans)
    print(f"Added note {n.gramps_id} → {obj.gramps_id}")
    return f"Add note to {obj.gramps_id}"


def cmd_tag(db, a, trans):
    tag = db.get_tag_from_name(a.tag)
    if tag is None:
        tag = Tag()
        tag.set_name(a.tag)
        db.add_tag(tag, trans)
    done = []
    for gid in a.ids:
        kind, obj = get(db, gid)
        if a.remove:
            obj.remove_tag(tag.handle)
        else:
            obj.add_tag(tag.handle)
        commit(db, kind, obj, trans)
        done.append(obj.gramps_id)
    print(f"{'Untagged' if a.remove else 'Tagged'} {', '.join(done)} {a.tag!r}")
    return f"Tag {a.tag}"


def cmd_remove_event(db, a, trans):
    _, ev = get(db, a.id)
    for cls, h in list(db.find_backlink_handles(ev.handle)):
        kind = cls.lower()
        obj = getattr(db, f"get_{kind}_from_handle")(h)
        obj.set_event_ref_list([r for r in obj.get_event_ref_list() if r.ref != ev.handle])
        if kind == "person":
            fix_vitals(db, obj)
        commit(db, kind, obj, trans)
    db.remove_event(ev.handle, trans)
    print(f"Removed event {a.id}")
    return f"Remove event {a.id}"


# ---------------------------------------------------------------- cli

READ = {"find": cmd_find, "show": cmd_show, "sources": cmd_sources}
WRITE = {"add-person": cmd_add_person, "set-name": cmd_set_name, "add-name": cmd_add_name,
         "add-event": cmd_add_event, "edit-event": cmd_edit_event, "remove-event": cmd_remove_event,
         "add-source": cmd_add_source, "cite": cmd_cite, "attach-media": cmd_attach_media,
         "link-parents": cmd_link_parents, "link-spouse": cmd_link_spouse,
         "set-attr": cmd_set_attr, "add-note": cmd_add_note, "tag": cmd_tag}


def build_parser():
    ap = argparse.ArgumentParser(prog="gt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", default=DEFAULT_TREE)
    ap.add_argument("--no-export", action="store_true", help="don't refresh tree/ after a write")
    ap.add_argument("--dry-run", action="store_true", help="run a write command but discard the changes")
    # Global flags are accepted before or after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tree", default=argparse.SUPPRESS)
    common.add_argument("--no-export", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    s = sub.add_parser("find", help="search people by name/ID words")
    s.add_argument("query")
    s = sub.add_parser("show", help="show any object by Gramps ID")
    s.add_argument("id")
    sub.add_parser("sources", help="list sources")

    s = sub.add_parser("add-person")
    s.add_argument("--given", required=True)
    s.add_argument("--surname", default="")
    s.add_argument("--gender", default="U", choices=list("MFUmfu"))
    s.add_argument("--birth", help='"DATE @ PLACE", either part optional')
    s.add_argument("--death", help='"DATE @ PLACE"')
    s.add_argument("--fsid", help="FamilySearch person ID, stored as attribute FSFTID")

    s = sub.add_parser("set-name", help="edit primary name / gender")
    s.add_argument("id")
    s.add_argument("--given")
    s.add_argument("--surname")
    s.add_argument("--prefix", help="real surname prefix like 'van', 'de'")
    s.add_argument("--gender", choices=list("MFUmfu"))

    s = sub.add_parser("add-name", help="alternate name (married name, alias…)")
    s.add_argument("id")
    s.add_argument("--surname", required=True)
    s.add_argument("--given")
    s.add_argument("--type", default="Married Name", choices=["Married Name", "Also Known As", "Birth Name"])

    s = sub.add_parser("add-event", help="add event to person or family")
    s.add_argument("id")
    s.add_argument("type", help="Birth, Death, Marriage, Census, Residence, Burial, Baptism, Immigration, …")
    s.add_argument("--date")
    s.add_argument("--place")
    s.add_argument("--desc")
    s.add_argument("--cite", help="existing citation ID to attach")
    s.add_argument("--also", help="comma-separated person IDs who share the event (e.g. census household)")

    s = sub.add_parser("edit-event")
    s.add_argument("id")
    s.add_argument("--date", help='"" clears')
    s.add_argument("--place", help='"" clears')
    s.add_argument("--desc")

    s = sub.add_parser("remove-event")
    s.add_argument("id")

    s = sub.add_parser("add-source")
    s.add_argument("--title", required=True)
    s.add_argument("--author")
    s.add_argument("--pubinfo")
    s.add_argument("--repo", help="repository name, e.g. FamilySearch")
    s.add_argument("--repo-web", action="store_true", help="repository is a website")

    s = sub.add_parser("cite", help="create a citation of SOURCE and attach it to targets")
    s.add_argument("source")
    s.add_argument("targets", nargs="*", help="event/person/family IDs the citation supports")
    s.add_argument("--page", help="exact locator within the source")
    s.add_argument("--date", help="date of the record")
    s.add_argument("--confidence", default="normal", choices=list(CONFIDENCE))
    s.add_argument("--url")
    s.add_argument("--media", help="path under media/ of the record image")

    s = sub.add_parser("attach-media")
    s.add_argument("id")
    s.add_argument("path")
    s.add_argument("--desc")

    s = sub.add_parser("link-parents")
    s.add_argument("child")
    s.add_argument("--father")
    s.add_argument("--mother")

    s = sub.add_parser("link-spouse")
    s.add_argument("id1")
    s.add_argument("id2")

    s = sub.add_parser("set-attr", help="set attribute, e.g. FSFTID")
    s.add_argument("id")
    s.add_argument("type")
    s.add_argument("value")

    s = sub.add_parser("add-note")
    s.add_argument("id")
    s.add_argument("text")
    s.add_argument("--research", action="store_true", help="note type Research")

    s = sub.add_parser("tag")
    s.add_argument("tag")
    s.add_argument("ids", nargs="+")
    s.add_argument("--remove", action="store_true")
    return ap


class DryRun(Exception):
    pass


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        if a.cmd in READ:
            with tree(a.tree, write=False) as db:
                READ[a.cmd](db, a)
            return 0
        with tree(a.tree, write=True) as db:
            try:
                with DbTxn(f"gt {a.cmd}", db) as trans:
                    msg = WRITE[a.cmd](db, a, trans)
                    trans.set_description(msg or a.cmd)
                    if a.dry_run:
                        raise DryRun
            except DryRun:  # exception inside DbTxn => Gramps rolls the transaction back
                print("(dry run — changes rolled back)")
                return 0
        if not a.no_export:
            subprocess.run([str(ROOT / "tools" / "export.sh"), a.tree], check=False,
                           stdout=subprocess.DEVNULL)
            print("tree/ snapshot refreshed — review with `git diff tree/`")
        return 0
    except GtError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
