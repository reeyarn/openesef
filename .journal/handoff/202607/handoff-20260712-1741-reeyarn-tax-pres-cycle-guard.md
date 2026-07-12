# Handoff — tax-pres-cycle-guard — 2026-07-12
**Status:** DONE (crash fix shipped); one follow-up spun out (base_sets dedup)

## Question
Does `TaxonomyPresentation` parse all 18 known cyclic-linkbase filings without crashing, while leaving the concept output byte-identical for the 10,113 filings that already parse?

## Answer
**Yes, on both counts.** Commit `6439c60`.

- **18/18** previously-crashing filings parse, **0 segfaults**, all with non-empty `concept_df`.
  `role_code == is_primary_statement` on all 18 — including `350798/2021`, the filing whose
  cached pickle failed the oracle and could not be repaired by any workaround. The
  cache-based recovery script is now obsolete.
- **Regression gate: 40/40 byte-identical `concept_df`** (33,334 rows) between the old `.so`
  and the new one, on filings that already parsed. The guard changes nothing for acyclic
  filings — it is path-scoped, not global.

The fix is a **path-scoped** cycle guard in `_traverse` (`tax_calc_df`), mirroring the `stack`
idiom `BaseSet.get_branch_members` already uses — which is precisely why the presentation side
never crashed while the calculation side did. `process_table_structure` had the same unguarded
shape and was guarded identically. `process_children` is also unguarded but is dead code.

### Answers to the handoff's UNVERIFIED items
1. **Other unguarded recursions?** Audited by AST. Only `_traverse` (fixed),
   `process_table_structure` (guarded prophylactically; never fires on this corpus) and
   `process_children` (dead, no callers). Everything else already carries a visited set.
2. **Presentation or calculation linkbase?** **Calculation**, in all 18. Zero presentation
   cycles in the corpus. e.g. Telekom Austria:
   `OtherComprehensiveIncome -> ReclassificationAdjustments... -> OtherComprehensiveIncome`.
3. **Was a guard REMOVED?** **No.** `_traverse` has never appeared in any commit — the whole
   recursive BaseSet branch was *uncommitted working-tree code*. HEAD does **not** crash on the
   18 filings, because HEAD's `tax_calc_df` never walks `chain_dn` at all. The old pickles
   parsed for that reason, not because a guard existed. (Confirmed by the user: no guard was
   ever written.)
4. **Cyclic vs. absurdly deep?** **Proven cyclic**, not inferred: an *iterative* three-colour
   DFS (depth cannot fool it) finds real back-edges. No recursion-limit argument needed.

## 1. DELIVERABLE — target state

**Organizing principle.** `openesef/engines/tax_pres_py.py`'s `_traverse()` walks a concept chain by unguarded recursion. When the chain contains a **cycle** (a concept that is its own ancestor), it recurses forever. Compiled via Cython it blows the C stack and **SIGSEGVs**; in pure Python it raises `RecursionError`. Both are the same bug. The fix is a **path-scoped visited set** — not a global one, because the chain is legitimately a DAG (a concept may appear under two different parents, and that must still emit both records). Only a node that is *its own ancestor on the current path* is a cycle.

This is not a cosmetic robustness fix. Downstream (`proj_esef`, the ESEF XBRL paper), the segfault does not surface as an error — it **hangs the whole pipeline**, because a `multiprocessing.Pool` worker that dies without returning leaves `imap_unordered` waiting forever on a result that will never arrive. An 80-minute parse of 10,287 filings appeared to complete 10,268 of them and then sat at "7 seconds remaining" indefinitely. The crash is silent; the symptom is a deadlock.

### The bug, exactly

`openesef/engines/tax_pres_py.py:1583-1598` (current):

```python
self_traverse = []
def _traverse(parent_concept, bs_key):
    children = parent_concept.chain_dn.get(bs_key, [])
    for child_node in children:
        rec = {
            'role': role, 'role_name': role_name,
            'from_qname': str(parent_concept.qname),
            'to_qname': str(child_node.Concept.qname),
            'weight': float(child_node.Arc.weight) if hasattr(child_node.Arc, 'weight') else 1.0,
            'order': float(child_node.Arc.order) if child_node.Arc.order is not None else None
        }
        self_traverse.append(rec)
        _traverse(child_node.Concept, bs_key)      # <-- no cycle guard
for node in chain_dn:
    _traverse(node.Concept, bs_key)
```

### Target

```python
self_traverse = []
def _traverse(parent_concept, bs_key, _path=None):
    # PATH-scoped, not global: the chain is a DAG. A concept legitimately appears
    # under two parents and must still emit both records. Only a concept that is
    # its own ANCESTOR ON THE CURRENT PATH is a cycle. A global `seen` set would
    # silently DROP legitimate records and change output for every filing.
    if _path is None:
        _path = set()
    key = str(parent_concept.qname)
    if key in _path:
        logger.warning("cycle in chain_dn at %s (role %s) -- pruned", key, role)
        return
    _path.add(key)
    try:
        for child_node in parent_concept.chain_dn.get(bs_key, []):
            self_traverse.append({...unchanged...})
            _traverse(child_node.Concept, bs_key, _path)
    finally:
        _path.discard(key)          # pop on exit -- this is what makes it path-scoped
for node in chain_dn:
    _traverse(node.Concept, bs_key)
```

**Grep for other unguarded recursions in the same file before you stop.** `_traverse` is the one that crashes on our corpus, but if the module walks `chain_dn` / `chain_up` recursively anywhere else, the same cycle will reach it.

### Build chain (get this wrong and your fix silently does nothing)

`setup.py:32-34` **copies `openesef/engines/tax_pres_py.py` -> `openesef/engines/tax_pres.pyx`**, then cythonizes to `tax_pres.cpython-311-x86_64-linux-gnu.so`.

- **Edit `tax_pres_py.py`. It is the source of truth.**
- `tax_pres.pyx` is GENERATED and will be overwritten — editing it is wasted work.
- `tax_pres.py` (Dec 2025) is a stale third copy; `from openesef.engines.tax_pres import ...` resolves to the **`.so`**, which shadows it.
- After editing, **rebuild the `.so`**, or `ureg_3020` keeps importing the old compiled module and nothing changes.

## 2. TASK LIST (ordered)

- [ ] T1 Reproduce the crash, both ways, before changing anything. Use the smallest file
      (`141239/2022`, 276 KB) so the loop is fast.
      (verify: compiled path exits **139 (SIGSEGV)**; pure-Python path raises
      `RecursionError` in `_traverse`. Both must reproduce or you are not looking at
      the bug I found.)
- [ ] T2 Confirm it is a CYCLE and not merely a deep tree — do not skip this, it decides
      the fix. Set `sys.setrecursionlimit(100_000)` and run the traversal on a thread
      with `threading.stack_size(512*1024*1024)`, using the pure-Python module.
      (verify: it STILL raises `RecursionError` / never terminates. If instead it
      completes, the tree is merely deep, the correct fix is different, and this whole
      handoff is wrong — say so and stop.)
- [ ] T3 Implement the path-scoped cycle guard in `openesef/engines/tax_pres_py.py`
      `_traverse` (see §1). Log each pruned cycle at WARNING with the qname and role;
      do not swallow it silently.
      (verify: `grep -n "_path" openesef/engines/tax_pres_py.py` shows the guard)
- [ ] T4 Rebuild the compiled extension in the `pyesef` env.
      `cd ~/Dropbox/Codes/openesef_repo && ~/anaconda3/envs/pyesef/bin/pip install -e . --force-reinstall --no-deps`
      (verify: `tax_pres.cpython-311-x86_64-linux-gnu.so` mtime is NEW; and
      `~/anaconda3/envs/pyesef/bin/python -c "from openesef.engines.tax_pres import TaxonomyPresentation; print('ok')"`)
- [ ] T5 Parse all 18 filings in §4 with the rebuilt `.so`.
      (verify: **18/18 succeed, zero segfaults**, each returns a non-empty `concept_df`.
      Print rows + `is_primary_statement` count per filing.)
- [ ] T6 **REGRESSION GATE — the important one.** The fix must not change output for
      filings that already parse. Pick >= 30 filings that parse today (any
      `data/bundesanzeiger/public/<gvkey>/<year>/*.zip` not in §4), parse each with the
      OLD `.so` and the NEW `.so`, and diff `concept_df`.
      (verify: **byte-identical `concept_df` on every one**. If any differs, your visited
      set is global rather than path-scoped and it is dropping legitimate DAG records.
      Stop and fix it; do NOT proceed.)
- [ ] T7 Report back to `proj_esef` (see §5 Couplings). The 18 filings must then be
      re-parsed there with `ureg_3020`, which is BLOCKED on this fix.
- [ ] T8 [GATE — ask user] Push to the openesef upstream / release a version? This repo
      is Dropbox-synced and shared with Philipp; a rebuilt `.so` changes his environment
      too. Confirm before publishing.

## 3. HARD RULES for the executor

1. **Edit `tax_pres_py.py`, never `tax_pres.pyx`** (generated by `setup.py:32-34`) and never
   `tax_pres.py` (stale, shadowed by the `.so`).
2. **You MUST rebuild the `.so` after editing.** Python imports the compiled module. An
   unrebuilt fix is a no-op that looks like a fix.
3. **Path-scoped visited set, not global.** A global `seen` changes output for every
   filing by dropping legitimate DAG re-visits. T6 is the gate that catches this; do not
   weaken T6 to make a global set pass.
4. **Use the `pyesef` conda env** (`~/anaconda3/envs/pyesef/bin/python`), python 3.11.11,
   numpy 2.2.6, Cython 3.0.12. `openesef` is installed there as an **editable** install
   pointing at this repo (`pip show openesef` -> *Editable project location*). System
   python does NOT have openesef.
5. **Set `TMPDIR` off the root disk.** ESEF ZIPs extract to `tempfile`; `/` on the Gaming
   PC has repeatedly hit 100% of 120 GB. Use `TMPDIR=/mnt/proj_esef/data/_tmp_parse`.
   A full disk makes the parse fail in confusing ways.
6. **Do not invent numbers.** Every "18/18 parsed" or "byte-identical" claim comes from a
   run you executed. The figures in §4 were verified on 2026-07-12 but re-derive them.
7. **This repo is shared** (Dropbox, Philipp uses it). Committing a rebuilt `.so` changes
   his environment. T8 gates that.

## 4. Verified facts

**Confirmed (2026-07-12, this session, on the Gaming PC):**

- Crash site: `ureg_3020_classify_concepts.py:317` -> `tp = TaxonomyPresentation(tax)`.
  Python faulthandler stack at abort points there.
- Compiled `.so`: **exit 139, SIGSEGV**, after "taxonomy loaded OK".
- Pure Python (`openesef.engines.tax_pres_py`): `RecursionError: maximum recursion depth
  exceeded` at `_traverse(child_node.Concept, bs_key)`, "[Previous line repeated 992 more
  times]".
- **Genuinely cyclic, not deep**: at `sys.setrecursionlimit(100_000)` with a 512 MB thread
  stack, it STILL fails to terminate.
- Environment: `pyesef` env, python 3.11.11, numpy 2.2.6, Cython 3.0.12; openesef
  **0.3.8.29**, editable install -> `~/Dropbox/Codes/openesef_repo`.
- A recompile ALONE does not fix this. The first hypothesis was a numpy-2 ABI break in a
  stale `.so`; it is not. Pure Python, which has no ABI at all, fails the same way. Do not
  spend time recompiling and hoping.

**The 18 crashing filings** (all under `/mnt/proj_esef/data/bundesanzeiger/public/`).
Note the sizes: this is NOT a volume problem — the two smallest are 276 KB and 180 KB,
smaller than a typical healthy 11 MB filing.

| gvkey/year | size | ZIP |
|---|---|---|
| 141239/2022 | **276K** | `141239/2022/TelekomAustriaAG-2022-12-31.zip` ← **use this to iterate** |
| 287404/2021 | **180K** | `287404/2021/esef_OrzelBialy_2021-12-31_pl.zip` ← second-smallest |
| 243198/2022 | 1.3M | `243198/2022/549300TGIVUUMY40MZ05-2022-12-31.zip` |
| 350798/2021 | 2.6M | `350798/2021/485100EOK8ED6FMU4R55-2021-12-31_en.zip` ← **see §5, this one is special** |
| 287404/2023 | 4.0M | `287404/2023/esef-OrzelBialy-2023-12-31-pl.zip` |
| 287404/2022 | 4.6M | `287404/2022/esef_OrzelBialy_2022-12-31_pl.zip` |
| 325016/2022 | 6.8M | `325016/2022/815600F8217BC7733697-2022-12-31.zip` |
| 274668/2021 | 11M | `274668/2021/959800QETXHEMRSX9V59-2021-12-31-es.zip` |
| 317891/2023 | 12M | `317891/2023/549300CJMQNCA0U4TS33-2023-12-31AR.zip` |
| 223500/2021 | 14M | `223500/2021/635400DTNHVYGZODKQ93-2021-12-31.zip` |
| 203379/2023 | 17M | `203379/2023/635400FQKB6QXERQOC74-2023-12-31-en.zip` |
| 100743/2024 | 20M | `100743/2024/Bekaert Annual Report 2024.zip` |
| 203379/2024 | 26M | `203379/2024/635400FQKB6QXERQOC74-2024-12-31-en.zip` |
| 317891/2024 | 26M | `317891/2024/549300CJMQNCA0U4TS33-2024-12-31-0-FR.zip` |
| 203379/2022 | 46M | `203379/2022/635400FQKB6QXERQOC74-2022-12-31-en.zip` |
| 349271/2024 | 52M | `349271/2024/894500FOM6WHY0KFW309-2024-12-31-0-fr.zip` |
| 277939/2023 | 71M | `277939/2023/969500EQZGSVHQZQE212-2023-12-31-fr.zip` |
| 277939/2024 | 96M | `277939/2024/969500EQZGSVHQZQE212-2024-12-31-0-fr.zip` |

Filers span AT / PL / BE / ES / FR — this is not one broken vendor. Multiple issuers ship
cyclic linkbases, so the guard is the right fix, not a per-filing exclusion.

**UNVERIFIED (check before acting):**

1. Whether `_traverse` is the ONLY unguarded recursion in `tax_pres_py.py`. I found the one
   that crashes on this corpus; I did not audit the module. Grep before you declare victory.
2. Whether the cycle is in the **presentation** or **calculation** linkbase. The crashing
   `_traverse` sits in the `calc_records` block, but `TaxonomyPresentation.__init__` builds
   both. Determine which, because it changes what you log.
3. Whether these filings parsed successfully under some EARLIER openesef. They have old
   `concepts.p.gz` pickles on disk (v2026.0427a), so *something* parsed them once. Either
   an older version had a guard, or they were parsed on a different machine. Worth 10
   minutes of `git log` — if a guard was REMOVED, that is the real story.
4. Whether the 512 MB stack in T2 is enough to distinguish "cyclic" from "absurdly deep".
   I am confident (100k frames did not finish) but it is an inference, not a proof. A
   direct cycle detection (walk `chain_dn` iteratively, look for a repeat) would settle it.

## 5. Risks, couplings, ruled-out

**Couplings (this fix does not stand alone):**
- **`proj_esef` is BLOCKED on this.** Its `_anchoring.py` was bumped to `v2026.0712a` to
  retain `statement_role_code`, which forced a full re-parse. 10,113 of 10,134 EU filings
  re-parsed; **these 18 could not**. Until they parse, `ureg_3080`'s GATE A raises (by
  design) because those filings would enter the concept inventory with NULL role codes.
  After T5 passes, `proj_esef` must run:
  `cd /mnt/proj_esef/code_fse && TMPDIR=/mnt/proj_esef/data/_tmp_parse ~/anaconda3/envs/pyesef/bin/python ureg_3020_classify_concepts.py --workers 8`
  (no `--force`; the version sentinel skips the 10,113 already done).
- **`/mnt/proj_bmcg` German filings** go through `ureg_3021`, a SEPARATE parse path that
  also routes through `tag_concepts`. If any of the 1,715 German filings is also cyclic, it
  will crash the same way. Nobody has checked. Check it while you are here.

**`350798/2021` is special — read this before you touch it.**
17 of the 18 can have their `statement_role_code` recovered from their existing cached
pickles (I verified the recovery against an oracle: `code.notna()` must equal the stored
`is_primary_statement`, and it does, on 17/18). **`350798/2021` FAILS that oracle on 2
rows** — its cached pickle cannot be repaired. It is the one filing that genuinely REQUIRES
this parser fix rather than a workaround. **Use it as your final acceptance test.**

**Ruled out (do not retry — I already did these):**
- *Recompiling the `.so` to fix a suspected numpy-2 ABI break.* Plausible, and wrong. Pure
  Python has no ABI and fails identically. The `.so` is not stale; the algorithm is broken.
- *Raising the recursion limit.* Fails at 100,000 frames with a 512 MB stack.
- *Blaming the full root disk.* `/` was at 100% during the first run and the deadlock
  looked disk-related. It is not — the crash reproduces with 8.8 GB free.
- *Assuming it is a size/timeout problem.* The two smallest filings in the corpus are among
  the crashers.

**Watchouts:**
- A `multiprocessing.Pool` worker that segfaults makes `imap_unordered` **hang forever**.
  So this bug presents as a HANG with a cheerful tqdm ETA, not as an error. If you see the
  parse stall near the end, that is this. (`proj_esef` should arguably move to
  `concurrent.futures.ProcessPoolExecutor`, which raises `BrokenProcessPool` instead of
  deadlocking — worth raising there, out of scope here.)
- Do NOT run `ureg_3020` with `--limit N`: it rewrites `data/ureg_3020_filing_summary.parquet`
  with only N rows, clobbering the manifest. (I did this and had to restore from git.)

## 6. Progress log

- Root cause isolated 2026-07-12 (evidence in §4). No code changed in this repo.
- `proj_esef` side, branch `enforce-is_numeric`: `_anchoring.py` bumped to `v2026.0712a`;
  `ureg_3020` re-parse ran 10,113/10,134; the 18 above are the blockers.
- A cache-based recovery for 17 of the 18 exists at
  `/tmp/.../scratchpad/recover_segfault_filings.py` (oracle-verified). It is a WORKAROUND,
  not the fix, and it does not save `350798/2021`.

## Implied TODOs

### 1. proj_esef: re-parse the 18 (UNBLOCKED — do this next)
```
cd /mnt/proj_esef/code_fse && TMPDIR=/mnt/proj_esef/data/_tmp_parse \
  ~/anaconda3/envs/pyesef/bin/python ureg_3020_classify_concepts.py --workers 8
```
No `--force` (the version sentinel skips the 10,113 already done). Do NOT pass `--limit N` —
it rewrites the manifest with only N rows.

### 2. OPEN: `base_sets` registers every network TWICE (pre-existing, NOT fixed)
Discovered while auditing the crash. `tax.base_sets` is populated by two independent
mechanisms that register the SAME (arc, role):
  - `xlink.py:conn_cc` -> `BaseSet` under a STRING key; builds `chain_dn`/`chain_up`.
  - `taxonomy.py:compile_{presentation,calculation}_networks` -> `XLink` under a TUPLE key,
    with a synthesized `.relationships` list.
`tax_pres` walks both, so **every concept row is emitted twice**. Measured: rows double
(170 -> 340) while UNIQUE (concept_qname, statement_name) is unchanged (95 -> 95).

**Consequences:**
- `proj_esef`: harmless — `tag_concepts()` deduplicates. Its metrics are provably unchanged
  (primary/role_code counts identical with and without the dedup).
- **`MDIS`: NOT harmless.** `mdis_1101_read_xbrl.py:739` sets
  `num_concepts_sop = len(sop_df)` — a RAW row count, no dedup — which feeds the means and
  quantiles in `mdis_1222_tb_3_4_secaccfreq.py` (Tables 3/4). The duplication inflates that DV.

**A fix was attempted and REVERTED — do not naively retry it.** Deduping by preferring the
BaseSet representation passes on ESEF (8/8 filings: rows halve, unique + statement counts
preserved) but **FAILS on EDGAR**: AAPL 2020 loses **210 unique concepts and 8 statements**
(891 -> 681 unique). The two representations have *asymmetric, filing-family-dependent*
coverage — neither is a superset:
  - BaseSet-only: all `definitionArc` networks; on EDGAR the XLink links carry
    `relationships == 0` yet still yield concepts the BaseSet walk misses.
  - XLink-only: arc-less role stubs (`...Details/Policies/Tables`), e.g. 16 of 22 roles on
    `015846/2024`. `conn_cc` is arc-driven, so it correctly never builds a BaseSet for them.
Any real fix must be validated on **both** ESEF and EDGAR corpora. Gate: unique
(concept_qname, statement_name) and statement count must be preserved on both.

### 3. OPEN: `/mnt/proj_bmcg` German filings (1,715) never checked for cycles
They go through `ureg_3021`, a separate parse path that also routes through `tag_concepts`.
The rebuilt `.so` protects them, but nobody has confirmed whether any are cyclic.

### 4. GATE (needs user): publish?
The repo is Dropbox-synced and shared with Philipp, and **MDIS symlinks openesef's source
directly with no version pin**, so the rebuilt `.so` and both commits reach both consumers
immediately. Not pushed / not released.
