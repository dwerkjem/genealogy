TREE ?= Family Tree
PY   ?= uv run --quiet python

.PHONY: help venv hooks privacy gt export report media check snapshot restore new-project

help:
	@echo "make gt ARGS='find smith'   read/edit the tree (tools/gt.py; ARGS='-h' for commands)"
	@echo "make export        full copy -> gramps-db/full/, anonymized public copy -> tree/"
	@echo "make report        data-quality + gaps report for the tree"
	@echo "make media         check media/ naming and list the inbox"
	@echo "make check         export + report + media"
	@echo "make hooks         install the private-name commit guard (once per clone)"
	@echo "make privacy       audit HEAD for protected names"
	@echo "make snapshot      export, then commit tree/ + media/ + research/"
	@echo "make new-project SLUG=smith-ontario-origins   start a research project"
	@echo "make restore NAME='Restored'   rebuild a Gramps tree from the full local export"

# Gramps is a system package for Debian's Python 3.11, so the venv must be built
# on that interpreter with system site-packages visible.
venv:
	rm -rf .venv
	uv venv --python /usr/bin/python3 --system-site-packages
	uv sync

# Block commits containing names listed in .private-terms (git-ignored).
hooks:
	git config core.hooksPath tools/hooks

# Audit every tracked file at HEAD for protected names.
privacy:
	@python3 tools/hooks/check_private.py --all && echo "No protected names in HEAD."

gt:
	@$(PY) tools/gt.py --tree "$(TREE)" $(ARGS)

export:
	@tools/export.sh "$(TREE)"

report:
	@$(PY) tools/tree_report.py gramps-db/full/family-tree.gramps --media-root media

media:
	@$(PY) tools/media_check.py media

check: export report media

snapshot: export
	git add tree media research
	git commit -m "Tree snapshot $$(date +%F)" || echo "Nothing to commit."

new-project:
	@test -n "$(SLUG)" || { echo "usage: make new-project SLUG=short-slug"; exit 1; }
	@f=research/projects/$$(date +%Y-%m)-$(SLUG).md; \
	  test ! -e $$f || { echo "$$f exists"; exit 1; }; \
	  sed "s/{{DATE}}/$$(date +%F)/" templates/research-project.md > $$f; echo "Created $$f"

restore:
	@test -n "$(NAME)" || { echo "usage: make restore NAME='New tree name'"; exit 1; }
	gramps -C "$(NAME)" -i gramps-db/full/family-tree.gramps
