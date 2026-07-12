# Session Index

| datetime | user | keyword | branch | summary | files |
|---|---|---|---|---|---|
| 2026-07-12 18:28 | reeyarn | tax-pres-cycle-guard | master | Path-scoped cycle guard fixes SIGSEGV on 18 cyclic-linkbase filings; 18/18 parse, 40/40 regression-identical | openesef/engines/tax_pres_py.py, openesef/engines/tax_pres.pyx, .journal/handoff/202607/handoff-20260712-1741-reeyarn-tax-pres-cycle-guard.md |
| 2026-07-12 20:15 | reeyarn | parse-error-fixes | master | Percent-decode path fix (file-not-found); statement detection rewritten (0/23 missing, was 7/23) | openesef/base/pool.py, openesef/engines/tax_pres_py.py, .journal/handoff/202607/handoff-20260712-1955-reeyarn-location-keying.md |
| 2026-07-12 20:54 | reeyarn | esef-package-resolution | master | W3C bundled mirror; XML-comment linkbase abort (BIC calc 177→264); ESEF renamed-package recovery (JM calc 0→144) | openesef/base/pool.py, openesef/base/resolver.py, openesef/taxonomy/taxonomy.py, openesef/taxonomy/xlink.py, openesef/taxonomy/linkbase.py |
