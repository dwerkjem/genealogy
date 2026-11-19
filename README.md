# Genealogy

Local family tree. **Gramps** is where the tree is edited. **git** keeps its
history. Documents and research notes are plain files next to it.

```
gramps-db/          live Gramps database (git-ignored; Gramps is pointed here)
  backups/          Gramps' automatic on-exit backups
tree/               PUBLIC snapshot, committed: XML + .ged, `anonymous`-tagged people scrubbed
media/              record images & documents (Git LFS)
  _inbox/           drop new downloads here, then file them
  <Surname>/        filed documents, one folder per surname
research/
  todo.md           quick to-dos
  projects/         one file per research question (research plan + log)
templates/          research-project.md, citations.md (how to cite in Gramps)
imports/            raw GEDCOM pulls from FamilySearch etc. (git-ignored)
tools/              gt.py (edit the tree), export, report, media check
```

## The loop

1. **Pick a question.** `make new-project SLUG=smith-parents` creates
   `research/projects/YYYY-MM-smith-parents.md`. Keep it to one specific,
   answerable question.
2. **Search and log everything.** Record every search in the project's research
   log, including the ones that find nothing.
3. **Save what you find.** Download images to `media/_inbox/`, then rename and
   move them to `media/<Surname>/` (see naming below).
4. **Enter it in Gramps.** Add the fact as an *event*, add a *citation* to it
   (see `templates/citations.md`), and attach the media. FamilySearch tree
   profiles are leads; cite the records behind them, not the tree itself.
5. **Close Gramps and snapshot.** `make snapshot` exports the tree (anonymized public copy in
   `tree/`) and commits it along with media and research notes. `git log -p tree/` then shows
   the tree's history.
6. **Review now and then.** `make report` lists unsourced events, people with no
   parents (your research frontier), impossible dates, likely duplicates, missing
   or unattached media, and how complete your pedigree is.

Run `make` on its own to list all commands.

## Editing the tree outside the GUI (`gt`)

`tools/gt.py` edits the tree through Gramps' own database API, the same layer
the GUI uses. This lets Claude (or you) make edits from the terminal:

```
make gt ARGS="find smith"
make gt ARGS="show I0001"
make gt ARGS="add-person --given John --surname Smith --gender M --birth 'abt 1860 @ Toronto, Ontario, Canada' --fsid ABCD-123"
make gt ARGS="link-parents I0001 --father I0003 --mother I0004"
make gt ARGS="add-source --title 'Canada Census, 1921' --pubinfo 'FamilySearch database with images' --repo FamilySearch --repo-web"
make gt ARGS="add-event I0001 Census --date 1921-06-01 --place 'Toronto, Ontario, Canada' --also I0003,I0004"
make gt ARGS="cite S0000 E0002 --page 'district 123, p. 12, line 34' --url <ark> --media Smith/1921_Census_Smith-William_Toronto-ON.jpg"
```

Other commands: `set-name`, `add-name` (married name or alias), `edit-event`,
`remove-event`, `link-spouse`, `attach-media`, `set-attr`, `add-note`, `tag`,
`sources`. Add `--dry-run` to try a command without saving it. Run
`make gt ARGS=-h` for the full list.

Safety:
- Writes are refused while the tree is open in Gramps.
- Before each write, the database is copied to `gramps-db/backups/`. The last
  30 copies are kept.
- After each write, `tree/` is re-exported, so `git diff tree/` shows exactly
  what changed.

To undo a bad edit, copy a `pre-edit-*.db` backup over
`gramps-db/<tree-dir>/sqlite.db`.

Merging duplicates and bulk cleanup are still best done in the Gramps GUI.

## Python environment

The tools run with uv. Debian packages Gramps for its system Python 3.11, so
the venv is built on that interpreter with system packages visible. Use
`make venv` to (re)create it. A plain `uv venv` won't be able to import Gramps.

## Media naming

```
media/<Surname>/<Date>_<Type>_<Surname>-<Given>[_<Place>][_<n>].<ext>
```

- **Date:** `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or `undated`. Use the date of the
  event, not the date you downloaded it.
- **Type:** Birth, Baptism, Marriage, Divorce, Death, Burial, Obituary, Census,
  Military, Immigration, Naturalization, Passenger, Probate, Will, Land, Tax,
  Directory, Newspaper, Church, Photo, Letter, DNA, or Other.
- **File it under the main subject's surname.** For a woman, use her maiden
  name. For a household record, use the head of household.

Examples: `media/Smith/1921_Census_Smith-William_Toronto-ON.jpg`,
`media/Jones/1948-06-12_Marriage_Jones-Mary_2.pdf`.

`make media` lists files still in the inbox and any names that break the rule.

## Seeding from FamilySearch

FamilySearch has no built-in GEDCOM export for the Family Tree. Options, in
order of preference:

1. **getmyancestors**, an unofficial open-source tool. It downloads your
   ancestors as GEDCOM using your own FamilySearch login, which you type in
   yourself. Run it with uv:
   ```
   uvx getmyancestors --help
   uvx getmyancestors -u <fs-username> -i <your-FS-ID> -a 6 -d 1 -m -o imports/familysearch-$(date +%F).ged
   ```
   It isn't actively maintained and FamilySearch's login process changes, so it
   may break.
2. **Gramps FamilySearch gramplet**, a third-party Gramps add-on that syncs
   individual people.
3. **RootsMagic** (has a free edition). It is FamilySearch-certified, so it can
   sync your FamilySearch tree and then export a GEDCOM.

Then in Gramps: *Family Trees → Import* the `.ged` from `imports/`. Use
**Tools → Family Tree Processing → Merge** and **Find Possible Duplicate
People** to reconcile it with what's already in Gramps. Afterwards, run
`make check` and commit.

## One-time Gramps setup

- *Edit → Preferences → Family Tree → Base path for relative media paths* =
  `<this repo>/media`. This keeps media links relative, so
  they still work if the repo moves.
- *Edit → Preferences → Researcher*: fill in your details. They go into GEDCOM
  headers.
- The database location is set in `~/.gramps/gramps51/gramps.ini` (`[database]
  path`). A backup of the original file is at `gramps.ini.bak-2026-11-19`.

## Privacy

This repo is public. Real data stays local:

- `gramps-db/` holds the live database and `gramps-db/full/`, a complete
  export. Both are git-ignored; `make report` reads the full export.
- `tree/` is the public copy. On every export, people tagged **`anonymous`** in
  Gramps become "Anonymous" with no surname, and their events, dates, places,
  notes, media, attributes and citations are removed. Gender, family links and
  the tag itself stay, so the tree keeps its shape. Researcher details are
  always stripped. The work happens in a throwaway copy
  (`tools/anonymize.py`), so the real tree is never touched.
- **Tag every living person `anonymous`:** `make gt ARGS="tag anonymous I0012"`.
  `make report` counts "presumed living" people so you can spot any you've
  missed.
- **Commit guard:** names listed in `.private-terms` (git-ignored, one per line)
  block any commit whose files, filenames or message contain them. "First Last"
  also matches "Last-First", "Last, First" and so on. Run `make hooks` once per
  clone. `make privacy` audits everything already committed.
- Media files are committed under their file names, so don't file records of
  living people in `media/`.
- The commit email is GitHub's no-reply address (`git config user.email`).

## Restoring

`make restore NAME='Restored Tree'` builds a new Gramps tree from the full local
export, `gramps-db/full/family-tree.gramps`. Don't restore from `tree/`: it is
anonymized.
