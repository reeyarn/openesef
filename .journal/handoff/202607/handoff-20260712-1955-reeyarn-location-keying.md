# Handoff — location-keying — 2026-07-12
**Status:** open

## Question
Does every dict in openesef that is keyed by a document location use ONE canonical
key form, so that a schema/linkbase registered once is found again — with the 18
cyclic filings still parsing and `concept_df` unchanged on filings that already work?

## Answer
*To be filled by the session that completes this work.*

## 1. DELIVERABLE — target state

**Organizing principle.** A document's `location` in openesef is not merely "the file
to open". It is (a) the **key** under which the Schema/Linkbase is registered, (b) the
**identity** concepts are keyed by (`f'{sh.location}#{c.id}'`), and (c) the **base**
that locators join relative hrefs onto. Today the same document is written into some
dicts under one string form and looked up under a *different* form. When the two forms
disagree, nothing raises — the lookup simply misses, the document is re-parsed, and
locator hrefs fail to match concept keys, so **labels and relationships come back empty
with no error**. That silent-empty failure mode is what makes this worth fixing, and it
is the reason every task below is gated on a byte-comparison rather than on "it runs".

### The four key forms currently in circulation

| # | form | example | produced by |
|---|------|---------|-------------|
| A | raw href as written in the XML (relative, may be percent-encoded) | `96950018...-2020-12-31.xsd` | the filing |
| B | `file://` URI, **percent-encoded** | `file:///tmp/METROPOLE%20TV/x.xsd` | `pathlib.Path(...).as_uri()` — `pool.py:257,262,835,848,871,890,898` |
| C | bare filesystem path, **decoded** | `/tmp/METROPOLE TV/x.xsd` | `to_local_path()` — `pool.py:106` |
| D | `util.reduce_url(C)` — normalized path (identity for plain paths) | `/tmp/METROPOLE TV/x.xsd` | `util.reduce_url()` — `base/util.py:126` |

### The mismatches (all verified — see §4)

| dict | WRITTEN with | READ with | consequence |
|---|---|---|---|
| `pool.schemas` | **D** (`schema.py:85` `self.pool.schemas[resolved_location] = self`) | **B** at `pool.py:708` (`if resolved_href in self.schemas`) | check can NEVER hit → schema re-constructed every reference |
| `pool.linkbases` | **D** (`linkbase.py:72`) | **B** at `pool.py:739`, and `pool.py:755` `self.linkbases.get(resolved_href, ...)` | check can NEVER hit → linkbase re-parsed |
| `pool.discovered` | raw `location` (**A/C**) at `schema.py:45` | `f'{hash}_{resolved_href}'` (**B**) at `pool.py:596,698` | two unrelated key schemes in ONE dict |
| `taxonomy.schemas` | **C** (`taxonomy.py:257`, via `attach_schema(schema_path, sh)` at `pool.py:734`) | — | inconsistent with `pool.schemas` (D) |
| `taxonomy.concepts` | **D**`#id` (`taxonomy.py:338`) | locator href (`locator.py:18`, built from `linkbase.base`) | matches ONLY if `linkbase.base` is in the same space |
| `fbase.XmlFileBase` | `self.location = util.reduce_url(location)` → **D** | `self.base = os.path.split(location)[0]` → built from the **RAW argument**, not `self.location` (`fbase.py:75-77`) | base and location can diverge |

### Target

1. **One canonical form.** Choose **D** (`reduce_url` of a decoded bare path for local
   files; the absolute URL unchanged for `http(s)://`; `mem://...` unchanged). Add a
   single normalizer next to `to_local_path` in `openesef/base/pool.py`:

   ```python
   def canonical_location(location):
       """The ONE string form used as a key for a document, everywhere."""
       if not isinstance(location, str):
           return location
       if location.startswith(('http://', 'https://', 'mem://')):
           return location
       return util.reduce_url(to_local_path(location))   # file:// or bare path -> D
   ```

2. **Every read and every write of a location-keyed dict goes through it.** Concretely:
   - `pool.py:708` → `if canonical_location(resolved_href) in self.schemas:`
   - `pool.py:739` → `if canonical_location(resolved_href) in self.linkbases:`
   - `pool.py:755` → `self.linkbases.get(canonical_location(resolved_href), this_lb)`
   - `pool.py:727` → `self.schemas.get(canonical_location(schema_path), ...)`
   - `pool.py:734` → `self.current_taxonomy.attach_schema(canonical_location(schema_path), sh)`
   - `schema.py:45` / `linkbase.py` `discovered[location]` → key on `canonical_location(location)`
     **and** make `pool.py:596,698` use the same scheme (drop the `f'{hash}_{...}'`
     prefix, or apply the hash prefix in both places — pick one, do it in both).
   - `fbase.py:77` → `self.base = os.path.split(self.location)[0]` (use the normalized
     `self.location`, not the raw argument).

3. **`to_local_path()` stays as-is** — it is the decode step and is already committed and
   verified (`f4b796a`). `canonical_location()` wraps it; it does not replace it.

4. **No behaviour change on filings that already parse.** This is a keying refactor, not
   a semantics change. The gate in T5 is what proves it.

## 2. TASK LIST (ordered)

- [ ] **T0 [GATE — ask user]** (a) Is `ureg_3020_classify_concepts.py` still running?
      If yes, do NOT start T5/T6 until it finishes — it mutates the shared cache
      `/mnt/proj_esef/data/xbrl_cache` and will silently corrupt any before/after
      comparison (this exact confound already produced one false "7/40 regression").
      (b) Confirm it is acceptable to change `pool.discovered`'s key scheme, since it is
      the loop-guard — a wrong change here can reintroduce the endless-loop the inline
      comments at `pool.py:731` (`#<- Endless loop`) refer to.

- [ ] **T1** Build the frozen-cache regression harness BEFORE touching any code. Snapshot
      the cache so the live job cannot move it under you:
      `cp -a /mnt/proj_esef/data/xbrl_cache /mnt/proj_esef/data/_frozen_cache`
      (~4 GB, ~2 min). Every parse below must be run against the SNAPSHOT.
      (verify: `test -f /mnt/proj_esef/data/_frozen_cache/www.w3.org/2001/XMLSchema.xsd`)

- [ ] **T2** Capture the BASELINE at current HEAD (`f4b796a`) on the frozen cache: for
      >= 30 filings that parse today, dump `concept_df` to a canonical CSV and sha256 it.
      Canonicalisation is mandatory: `segment_axes` / `segment_members` are built as
      `list(<set>)` (`tax_pres_py.py:192-193`), so their ORDER varies with
      `PYTHONHASHSEED` and a raw hash differs on every run. Sort those cells, and set
      `PYTHONHASHSEED=0`.
      (verify: parse the SAME filing twice; the two sha256 values must be equal. If they
      are not, the harness is broken — fix it before trusting any later comparison.)

- [ ] **T3** Add `canonical_location()` to `openesef/base/pool.py` next to `to_local_path`
      (§1.1). Do not wire it in yet.
      (verify: `python -c "from openesef.base.pool import canonical_location as c; print(c('file:///tmp/a%20b/x.xsd'), c('http://x/y.xsd'), c('mem://z.xml'))"`
      → `/tmp/a b/x.xsd http://x/y.xsd mem://z.xml`)

- [ ] **T4** Wire it into every site listed in §1.2, one file at a time, in this order:
      `pool.py` → `schema.py` → `linkbase.py` → `fbase.py`. Order matters: `fbase.py:77`
      is read by `locator.py:13,16`, so changing it last means the earlier diffs are read
      against unchanged locator behaviour.
      (verify: `grep -n "in self.schemas\|in self.linkbases\|self.linkbases.get\|self.schemas.get\|attach_schema(\|discovered\[" openesef/base/pool.py openesef/taxonomy/schema.py openesef/taxonomy/linkbase.py`
      — every hit must pass its key through `canonical_location`)

- [ ] **T5 — REGRESSION GATE (the important one).** Re-run T2's >= 30 filings on the
      frozen cache and diff against the baseline.
      (verify: **byte-identical `concept_df` on every filing**. If any differs, a key
      space moved and you have changed semantics. Stop and fix; do NOT relax the gate.)

- [ ] **T6 — CYCLIC GATE.** Parse all 18 filings listed in §4 and confirm none crash.
      (verify: **18/18 exit 0, zero segfaults (exit 139)**, each returns a non-empty
      `concept_df`.)

- [ ] **T7 — IMPROVEMENT CHECK (this is what the refactor is FOR).** On the two
      space-in-path filings in §4, count extension concepts whose labels bound.
      (verify: `ext_labelled` must be **>= 7** for `347247/2021` and **>= 10** for
      `343851/2022` — i.e. no worse than HEAD. If the number DROPS to 0, the schema and
      linkbase key spaces have diverged again and you have reintroduced the original bug.)

- [ ] **T8** Report whether the dedup checks now actually hit — i.e. whether schemas and
      linkbases stop being re-parsed. Add a counter or a DEBUG log at `pool.py:708,739`.
      (verify: on any filing, the "already loaded" branch is taken at least once. If it
      is still never taken, the keys are STILL mismatched and T4 is incomplete.)

- [ ] **T9 [GATE — ask user]** Commit and/or push? The repo is Dropbox-synced with a
      collaborator, and `MDIS` symlinks openesef's source with **no version pin**, so any
      change reaches both consumers immediately.

## 3. HARD RULES for the executor

1. **`pool.py` is pure Python — do NOT rebuild the Cython extension for it.** Only
   `openesef/engines/tax_pres.pyx` is cythonized (`setup.py:32-34` copies
   `tax_pres_py.py` -> `tax_pres.pyx`). If you *do* touch `tax_pres_py.py`, you MUST run
   `~/anaconda3/envs/pyesef/bin/pip install -e . --force-reinstall --no-deps`, or the
   `.so` keeps the old code and your fix is a silent no-op.
2. **Never run a before/after comparison against `/mnt/proj_esef/data/xbrl_cache`.** The
   live parse job writes to it. Use the frozen snapshot from T1. This is not a
   theoretical risk: it already produced a false 7/40 "regression" in the session that
   wrote this handoff.
3. **Always set `PYTHONHASHSEED=0` and canonicalise set-derived columns before hashing.**
   Otherwise every run differs and the gate is noise (see T2).
4. **Set `TMPDIR` off the root disk**: `TMPDIR=/mnt/proj_esef/data/_tmp_parse`. `/` on
   this machine has repeatedly hit 100% of 120 GB; ESEF zips extract to `tempfile`.
5. **Use the `pyesef` conda env** (`~/anaconda3/envs/pyesef/bin/python`, 3.11.11).
   `openesef` is an editable install pointing at this repo. System python has no openesef.
6. **Do not invent numbers.** Every "N/N identical" or "labels bound" claim must come from
   a run you executed. The figures in §4 were measured on 2026-07-12; re-derive them.
7. **Do not "fix" the two known-broken things while you are in here** (they are separate
   handoffs): the `base_sets` double-registration, and the empty `label` column in
   `concept_df`. Touching them will contaminate the T5 gate.
8. **`git checkout -- <file>` is dangerous in this repo.** Several files carry
   *uncommitted* pre-existing work. Check `git status` before reverting anything; one
   file was already clobbered this way and had to be recovered from a dangling stash blob.

## 4. Verified facts

**Confirmed (2026-07-12, all by direct inspection or execution):**

- The four key forms and every mismatch in the §1 table were read directly from source:
  `schema.py:72,85` (`resolved_location = util.reduce_url(location)`, then
  `pool.schemas[resolved_location] = self`); `linkbase.py:72`; `pool.py:708,727,734,739,755`;
  `taxonomy.py:257,276,338`; `fbase.py:75-77`; `locator.py:13,16,18`.
- `pool.py:708` (`if resolved_href in self.schemas`) compares form **B** against a dict
  keyed in form **D**, so it can never hit. Same for `pool.py:739`.
- `util.reduce_url` is effectively the identity on a plain absolute path (`base/util.py:114-127`
  only collapses `.` and `..`), so form C and D coincide for local files. This is why the
  system limps along instead of failing loudly.
- **The silent-empty failure is real and measurable.** On the two filings below, the
  entity's own label linkbase bound ZERO labels before the `to_local_path` fix and binds
  them after — `concept_df` row count unchanged, so this was pure hidden data loss:

  | filing | zip | ext concepts | ext_labelled BEFORE | ext_labelled AFTER | rows |
  |---|---|---|---|---|---|
  | `347247/2021` | `5967007LIEEXZXHW3S18-2021-12-31.zip` (dir `Final ZIP file/`) | 10 | **0** | **7** | 520 |
  | `343851/2022` | `549300WCI347SOTFJB71-2022-12-31.zip` (dir `Volue Annual Report 2022/`) | 13 | **0** | **10** | 667 |

  Both have a SPACE in a directory name but correct LEI-based internal naming, which is
  what makes them the clean test case. Use them for T7.
- Percent-decoding is already fixed and committed (`f4b796a`, `to_local_path` at
  `pool.py:106`, used at 4 sites). Regression at the time: 7/7 byte-identical on a frozen
  cache; 33/40 identical through cache drift.
- **The 18 cyclic-linkbase filings** (for T6), all under
  `/mnt/proj_esef/data/bundesanzeiger/public/<gvkey>/<year>/*.zip`:
  `141239/2022`, `287404/2021`, `243198/2022`, `350798/2021`, `287404/2023`, `287404/2022`,
  `325016/2022`, `274668/2021`, `317891/2023`, `223500/2021`, `203379/2023`, `100743/2024`,
  `203379/2024`, `317891/2024`, `203379/2022`, `349271/2024`, `277939/2023`, `277939/2024`.
  They parse today (18/18, 0 segfaults) thanks to the cycle guard in `6439c60`.
- Reproduction recipe for any filing (this is what the harness must do):
  ```python
  import sys; sys.path.insert(0, "/mnt/proj_esef/code_fse")
  from ureg_3020_classify_concepts import extract_zip, find_entry_points
  from openesef.base import pool as opool
  from openesef.engines.tax_pres import TaxonomyPresentation
  root = extract_zip(zip_path, tmpdir)
  xsd, pre, folder = find_entry_points(root)
  tax = opool.Pool(cache_folder=FROZEN_CACHE, max_error=1024).add_taxonomy(
            entry_points=[xsd, pre], esef_filing_root=folder)
  df = TaxonomyPresentation(tax).concept_df
  ```
  Run each filing in its OWN subprocess: a segfault then returns 139 instead of hanging.

**UNVERIFIED (check before acting):**

1. Whether changing `pool.discovered`'s key scheme reintroduces the endless loop the code
   comments warn about (`pool.py:731` `#<- Endless loop`, `pool.py:702` `#<- Endless loop`).
   `discovered` is the loop-guard. Test on a filing with circular schema imports before
   trusting it. This is why T0(b) is a gate.
2. Whether `mem://` (the in-memory FS path, used by the `filings_xbrl_org` flow) survives
   the change. All testing behind this handoff used on-disk ESEF zips. `canonical_location`
   passes `mem://` through untouched by design — but that is an assertion, not a test.
   Exercise one `mem://` path before declaring done.
3. Whether the EDGAR path is affected. `pool.py` is shared with `openesef/edgar/loader.py`,
   but EDGAR locations are http-cached rather than `esef_filing_root`-relative. Parse one
   SEC filing (`load_xbrl_filing(ticker="AAPL", year=2020)`) and confirm `concept_df` is
   unchanged.
4. Whether making the dedup checks actually hit changes output. Today schemas/linkbases are
   silently re-parsed; once the checks work, the FIRST loaded object wins instead of the
   last. If two different objects were being registered under the same key, output could
   move. T5 is what catches this — if T5 fails, this is the first hypothesis to test.

## 5. Risks, couplings, ruled-out

**Couplings (move together or not at all):**
- `fbase.py:77` (`self.base`) and `locator.py:13,16` (which join onto `linkbase.base`) are
  one unit. Changing `base` without re-checking locator resolution silently breaks concept
  lookup — the exact failure this handoff exists to prevent.
- `schema.py:85` / `linkbase.py:72` (the WRITE) and `pool.py:708/739` (the READ) are one
  unit. Fixing only the read side turns a never-hitting check into a wrongly-hitting one.

**Ruled out (do not retry):**
- *Stripping `file://` with `re.sub` and passing the result to lxml.* That is the original
  bug — `as_uri()` percent-encodes, and the `%20`/`%2B` survives into the path. Fixed in
  `f4b796a`; do not reintroduce a bare `re.sub("file://", "", ...)` anywhere.
- *Recovering renamed ESEF packages by matching a file's role suffix* (e.g. binding a
  dangling `<LEI>.xsd` reference to the single `*.xsd` present). Implemented and reverted
  this session: the helper resolves correctly in isolation but is a **no-op in the actual
  pipeline** (identical sha), because the reference does not flow through that resolution
  path. Do not re-attempt without first tracing where the dangling href is actually
  resolved. Affected filing to study: `204796/2020` (METROPOLE TELEVISION) — its internal
  refs use the ESEF-mandated LEI name while the files on disk were renamed.

**Watchouts:**
- A `multiprocessing.Pool` worker that segfaults makes `imap_unordered` hang FOREVER. If a
  parse "stalls near the end", that is a crash, not slowness. Run parses in subprocesses
  and check for returncode 139.
- Workers import `pool.py` once at start. Editing `pool.py` while a parse job is running
  does NOT affect that job — it must be restarted to pick up changes.
- `.gitignore:216` excludes `/openesef/xbrl_schema`, so new files there are invisible to
  git. `openesef/xbrl_schema/www.w3.org/2001/XMLSchema.xsd` was added on disk this session
  (it stops a W3C 403 and 84 log errors) but is NOT committed. `git add -f` if you want it
  tracked. It changes no parse output — verified by toggling it on a frozen cache.

## 6. Progress log

- `f4b796a` — Fix "file not found": decode percent-encoded paths before opening them.
  Added `to_local_path()` (`pool.py:106`) and used it at the 4 sites that previously did
  `re.sub("file://", "", ...)`. This is the foundation `canonical_location()` builds on.
- `6439c60` — path-scoped cycle guard in `tax_pres` (the 18 filings above now parse).
- `084b78c`, `99b2ad7` — recorded pre-existing uncommitted work (BaseSet support in
  `tax_pres`; Pass 2 re-enable in `taxonomy.py`), flagged as not session-authored.
- No code was written for THIS handoff. The mismatch table in §1 is an audit result, not a
  change.

## Implied TODOs
*To be filled after the answer is known.*
