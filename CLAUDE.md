# Genealogy repo — notes for Claude

Read README.md for the layout and workflow. Key rules:

- **Gramps is the source of truth.** The live database is `gramps-db/` (git-ignored).
  **Edit it with `tools/gt.py`** (`uv run python tools/gt.py ...` or `make gt ARGS=...`).
  Never hand-edit `tree/` or `gramps-db/full/`; both are exports that the next
  write overwrites. `tree/` is the **public, anonymized** copy, and
  `gramps-db/full/` is the complete local one. Read real data from the full copy
  or with `gt show`.
- Before adding a person, `gt find` to avoid duplicates. Use `gt show` to check
  the result after a change. Cite every fact you add (`add-source` once per
  collection, `cite` per record), and attach the citation to the *event*.
- For several changes, use `--no-export` on all but the last command (the last
  one re-exports). Use `--dry-run` when unsure. Report what changed with
  `git diff tree/`.
- If `gt` lacks an operation, extend `tools/gt.py` using the Gramps API
  (`gramps.gen.lib`, `DbTxn`), not raw SQL. Test against a throwaway tree:
  set `GRAMPSHOME` to a scratch dir, then `gramps -C Test -i gramps-db/full/family-tree.gramps`.
- **The Gramps CLI can't open a tree while the GUI has it open.** Ask the user to
  close Gramps before `make export` / `make check`.
- Default tree name is `Family Tree` (`TREE=` in Makefile, or `GRAMPS_TREE`).
- **Python runs through uv.** The venv is system Python 3.11 with system
  site-packages, because Gramps is a Debian package. Use `make venv` to rebuild
  it, never a plain `uv venv`. Add dependencies with `uv add`, never pip.
- **Media naming** is enforced by `tools/media_check.py`. Keep README, that
  script, and `templates/` consistent when changing the convention.
- When filing media from `media/_inbox/`, rename it to the convention and move
  it with `git mv` if it's already tracked.
- Research projects follow `templates/research-project.md`. Log negative and nil
  searches too. Treat FamilySearch tree profiles as leads, not sources.
- **This repo is PUBLIC.** Tag every living person you add `anonymous`
  (`gt tag anonymous <IDs>`); the export then scrubs them from `tree/`. Never
  put real names of living people in committed files, examples or commit
  messages; use fictional names (Smith/Jones) in docs. The pre-commit guard
  (`.private-terms`, `make hooks`) enforces this for the user and parents.
  Never bypass it with `--no-verify`.
- **The data includes living people.** Never send names, dates, or places from
  the tree to external services without the user's say-so. Only the anonymized
  `tree/` copy may be published.
