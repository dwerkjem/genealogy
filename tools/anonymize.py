#!/usr/bin/env python3
"""Anonymize people tagged "anonymous" in a Gramps tree, IN PLACE.

Only ever run this against a throwaway copy. tools/export.sh imports the real
tree into a temporary GRAMPSHOME and runs this there before writing the
public snapshot in tree/.

For each tagged person:
  - primary name becomes "Anonymous" with no surname; alternate names dropped
  - events, notes, media, attributes, addresses, URLs, citations, and
    associations are removed (dates and places identify people too)
  - gender, family links, and the "anonymous" tag are kept, so the tree's
    shape survives
Events/notes/media/citations left unreferenced are deleted. Family events
(e.g. marriage) of families with an anonymous spouse are removed too. The
researcher/submitter block is always cleared.

Usage: GRAMPSHOME=<tmp> anonymize.py <tree name>
"""
from __future__ import annotations

import os
import sys

_stderr = os.dup(2)
os.dup2(os.open(os.devnull, os.O_WRONLY), 2)  # hide Gtk's C-level noise
sys.stderr = os.fdopen(_stderr, "w", buffering=1)

from gramps.gen.db import DbTxn  # noqa: E402
from gramps.gen.db.utils import open_database  # noqa: E402
from gramps.gen.lib import Name, Researcher, Surname  # noqa: E402

TAG = "anonymous"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    db = open_database(sys.argv[1])
    if db is None:
        print(f"Can't open tree {sys.argv[1]!r}", file=sys.stderr)
        return 1
    try:
        db.set_researcher(Researcher())
        tag = db.get_tag_from_name(TAG)
        if tag is None:
            print("anonymize: no people tagged 'anonymous'")
            return 0
        people = [p for p in db.iter_people() if tag.handle in p.get_tag_list()]
        anon = {p.handle for p in people}
        families = [f for f in db.iter_families()
                    if f.get_father_handle() in anon or f.get_mother_handle() in anon]
        events, notes, media, cites = set(), set(), set(), set()

        with DbTxn("anonymize", db) as trans:
            for p in people:
                events |= {r.ref for r in p.get_event_ref_list()}
                notes |= set(p.get_note_list())
                media |= {r.ref for r in p.get_media_list()}
                cites |= set(p.get_citation_list())
                for n in [p.get_primary_name()] + p.get_alternate_names():
                    cites |= set(n.get_citation_list())
                n = Name()
                n.set_first_name("Anonymous")
                sn = Surname()
                sn.set_primary(True)
                n.add_surname(sn)
                p.set_primary_name(n)
                p.set_alternate_names([])
                p.set_event_ref_list([])
                p.set_birth_ref(None)
                p.set_death_ref(None)
                p.set_note_list([])
                p.set_media_list([])
                p.set_citation_list([])
                p.set_attribute_list([])
                p.set_address_list([])
                p.set_url_list([])
                p.set_lds_ord_list([])
                p.set_person_ref_list([])
                db.commit_person(p, trans, change_time=p.change)  # keep timestamp => stable diffs

            for f in families:
                events |= {r.ref for r in f.get_event_ref_list()}
                notes |= set(f.get_note_list())
                media |= {r.ref for r in f.get_media_list()}
                cites |= set(f.get_citation_list())
                f.set_event_ref_list([])
                f.set_note_list([])
                f.set_media_list([])
                f.set_citation_list([])
                f.set_attribute_list([])
                db.commit_family(f, trans, change_time=f.change)

            def orphan(h):
                return not any(True for _ in db.find_backlink_handles(h))

            # Events first: removing them can orphan their citations/notes/media.
            for h in events:
                ev = db.get_event_from_handle(h)
                if ev and orphan(h):
                    cites |= set(ev.get_citation_list())
                    notes |= set(ev.get_note_list())
                    media |= {r.ref for r in ev.get_media_list()}
                    db.remove_event(h, trans)
            for h in cites:
                c = db.get_citation_from_handle(h)
                if c and orphan(h):
                    notes |= set(c.get_note_list())
                    media |= {r.ref for r in c.get_media_list()}
                    db.remove_citation(h, trans)
            for h in notes:
                if db.get_note_from_handle(h) and orphan(h):
                    db.remove_note(h, trans)
            for h in media:
                if db.get_media_from_handle(h) and orphan(h):
                    db.remove_media(h, trans)
        print(f"anonymize: {len(people)} people anonymized")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
