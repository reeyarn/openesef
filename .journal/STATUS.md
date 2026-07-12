# Project Status — 2026-07-12

## Phase
Active development / maintenance — current focus on SEC EDGAR XBRL support.
Parser robustness: cyclic-linkbase SIGSEGV, percent-encoded paths and primary-statement
detection all fixed; `base_sets` dedup and location-key normalisation still open.

## 🚨 MISSION CRITICAL — EDGAR fact_by_year.py Parsing Failures (2023–2025)

**Reported by:** Patron / primary downstream user (MDIS project)
**Severity:** Project-threatening — if unresolved, funding/support may be discontinued
**Report:** `../MDIS/data/openesef_missing_pickles_report.md`
**Loss list:** `../MDIS/data/dim_accounts_loss_list.csv`

**Problem:** `fact_by_year.py` fails to produce `calc_df.p.gz`, `fact_df.p.gz`,
`link_df.p.gz` pickles for 1,841 / 66,206 filings (2.8% overall). The failure
rate jumps to **~15% for 2023–2025** filings (685/4,532 in FY2023, 780/4,496
in FY2024, 32/211 in FY2025). Core 2009–2022 sample is 99.3% coverage.

**Suspected root causes:**
1. XBRL parsing failure in `xbrl_worker.py` (iXBRL, malformed XML, missing schemas, timeouts)
2. EDGAR index mismatch — `get_filing_info()` date_filed year vs fiscal year
3. Raw filing not downloaded by `edgarform.py`

**Pipeline:** `edgarform.py` → `fact_by_year.py` → `mdis_1104_xbrl_dim.py` → panel merge

**Action required:**
1. Diagnose failure modes on ~20 sample filings from loss list (2023–2024 priority)
2. Categorize errors (parse failure, missing schema, timeout, index mismatch, etc.)
3. Fix openesef or report unfixable losses with counts

---

## What's Done

`## What's Done` is a **milestone tree** whose top-level stages were defined
during project setup. Each `###` heading is a lifecycle stage — never rename
or reorder. Deliverables use `- [x]` (done) or `- [ ]` (not yet).

### 1. Core Architecture
- [x] Base XBRL data structures (elements, pools, cubes, resolvers)
- [x] Package scaffolding (pyproject.toml, setup.py, Cython build)
- [x] PyPI publishing pipeline (v0.3.8.29)
- [x] Repo converted to Claude Code collaboration workspace

### 2. XBRL Taxonomy Engine
- [x] Schema parsing (concepts, item types, simple types)
- [x] Linkbase parsing (presentation, calculation, definition, label)
- [x] Taxonomy packages and discovery
- [x] XDT (dimensional) support
- [x] Cycle guard for cyclic calculation linkbases — fixes SIGSEGV; 18/18 crashers parse, 40/40 regression-identical
- [x] Percent-decode document paths — fixes "file not found" on packages with a space/`+`/parens
- [x] Primary-statement detection: IFRS role number + ESEF Art.4 root anchor + multilingual — 0/23 missing (was 7/23)
- [ ] Dedup `base_sets` double-registration — reverted once; ESEF-safe but loses 210 concepts on EDGAR
- [ ] Canonicalise document-location keys — see handoff-20260712-1955-reeyarn-location-keying
- [ ] Recover ESEF packages whose files were renamed off the mandated LEI name (~24 filings)
- [ ] Table linkbase rendering
- [ ] Formula linkbase evaluation
- [x] US-GAAP taxonomy cache (2009–2026)
- [x] IFRS taxonomy support

### 3. Instance & iXBRL Parsing
- [x] Instance document parsing (facts, contexts, units)
- [x] DEI (Document and Entity Information) extraction
- [x] iXBRL format support
- [ ] Footnote linkbase processing

### 4. EDGAR Integration
- [x] EDGAR filing loader (ticker + year)
- [x] SGML parsing for filing packages
- [x] Financial statement extraction
- [ ] Improve EDGAR XBRL reliability and edge cases
- [ ] EDGAR filing text document support
#### Testing
- [ ] EDGAR integration tests
- [ ] Edge case coverage for SEC filings
#### Documentation
- [ ] EDGAR usage examples and guides
- [ ] API documentation for edgar module

### 5. ESEF Integration
- [x] Basic ESEF filing support
- [x] filings.xbrl.org API integration
- [ ] EU OAM data source support
#### Testing
- [ ] ESEF integration tests
#### Documentation
- [ ] ESEF usage examples

## Open Questions
- `concept_df`'s `label` column is empty for EVERY filing, although labels bind fine at the taxonomy level (5028/5055 concepts). A `tax_pres` bug, not a data one; nobody has looked at it.
- Document locations are used as dict KEYS in four different string forms (raw href / `file://` URI / bare path / `reduce_url`d path), so several "already loaded" checks can never hit and schemas/linkbases are silently re-parsed. Work order: `handoff-20260712-1955-reeyarn-location-keying.md`.
- The shared `xbrl_cache` is mutated by any running parse job, which silently invalidates before/after comparisons. Always A/B against a frozen snapshot.
- `openesef/xbrl_schema/www.w3.org/2001/XMLSchema.xsd` is on disk but gitignored (`.gitignore:216`) — `git add -f` if it should ship with the package. It stops a W3C 403 but changes no parse output.
- `tax.base_sets` registers every linkbase twice (BaseSet + XLink), so `tax_pres` emits every concept row twice. Harmless for proj_esef (`tag_concepts` dedups) but inflates MDIS's `num_concepts_sop` (a raw `len()`, feeds Tables 3/4). A union-dedup was built and reverted: safe on ESEF, loses 210 unique concepts + 8 statements on EDGAR. Any fix must be gated on BOTH corpora.
- Are any of the 1,715 German proj_bmcg filings cyclic? They use a separate parse path (`ureg_3021`) and were never checked; the rebuilt `.so` protects them, but nobody has confirmed.
- Publish/push gate: repo is Dropbox-synced with Philipp, and MDIS symlinks openesef source with no version pin — the rebuilt `.so` reaches both consumers immediately. Nothing pushed yet.
- What EDGAR edge cases are currently failing?
- Which engines/ modules need the most maintenance attention?
- Is the Cython tax_pres still providing meaningful speedup vs pure Python fallback?
