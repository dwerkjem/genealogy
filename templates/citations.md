# Citing sources in Gramps

Gramps splits a citation into a **Source** (the work, reused across many people)
and a **Citation** (where in that work, per fact). Rule of thumb: one Source per
record collection, one Citation per specific entry/image.

| Gramps field | What goes in it | Example |
|---|---|---|
| Source → Title | Collection name | Canada Census, 1921 |
| Source → Author | Creator/jurisdiction | Canada, Statistics Canada |
| Source → Pub. info | Publisher/database | FamilySearch database with images |
| Source → Repository | Where you accessed it | FamilySearch (type: Web site) |
| Citation → Volume/Page | Exact locator | Ontario, Toronto, district 123, sub-district 4, p. 12, line 34, William Smith household |
| Citation → Date | Date of the record (not access date) | 1921-06-01 |
| Citation → Confidence | How much you trust it *for this fact* | Normal / High |
| Citation → Attribute "URL" | Permalink (FamilySearch ARK) | https://familysearch.org/ark:/61903/1:1:XXXX-XXX |
| Citation → Attribute "Accessed" | Access date | 2026-11-19 |
| Citation → Media | The image in `media/` | 1921_Census_Smith-William_Toronto-ON.jpg |

Attach the citation to the **event** it proves (Birth, Census residence…), not
just to the person. `make report` flags events without citations.

## Confidence guide
- **Very high:** original record, primary information, direct evidence.
- **High:** original or good derivative, primary information.
- **Normal:** derivative (index/transcript) or secondary information.
- **Low:** family tradition, someone else's tree, conflicting evidence.
- **Very low:** a hint you haven't verified yet.

FamilySearch Family Tree profiles and other people's trees are **leads, not
sources**. Cite the records they point to, not the tree.
