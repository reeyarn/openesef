# Prompt History — reeyarn — 2026-07-12 20:54

1. `git push`
   (bash: `To https://github.com/reeyarn/openesef.git   fb21e1a..b2e2aaa  master -> master`)

2. [pasted parse log] `Failed to download http://www.w3.org/2001/xml.xsd: 403 Client Error: Forbidden ... Failed to attach schema: location=http://www.w3.org/2001/xml.xsd ... OSError: Error reading file '/mnt/proj_esef/data/xbrl_cache/www.w3.org/2001/xml.xsd': No such file or directory`

3. I just downloaded from my browser and saved in the folder

4. what is this error   1.28it/s]Error processing calculation linkbase file:///mnt/proj_esef/data/_tmp_parse/esef_qr50ucaa/bic-2023-12-31/www.bic.com/bic-2023-12-31_cal.xml: '_cython_3_1_4.cython_function_or_method' object has no attribute 'lower'

5. [pasted] `Cyclic calculation relationship pruned at ifrs-full:ProfitLossFromOperatingActivities (role http://www.bekaert.com/role/KasstroomoverzichtindirectmethodeStatement)` (and the same for `.../StatementofcashflowsindirectmethodStatement`)

6. [pasted parse log] `Failed to load linkbase: location=/mnt/proj_esef/data/_tmp_parse/esef_x1rytt9z/MICHELIN-2021-12-31-fr/www.michelin.com/549300SOSI58J6VIW052-2021-12-31_ref.xml ... No such file or directory` (+ full traceback)

7. does it mean that ESEF without _ref.xml still processed to the end despite the error

8. [pasted parse log] `Failed to load linkbase: .../JM-2023-12-31-sv/www.jm.se/529900X0UEM9DOM6FK12-2023-12-31_pre.xml` — and the same for `_def.xml`, `_cal.xml`, `_lab-sv.xml`, plus `Failed to attach schema: .../529900X0UEM9DOM6FK12-2023-12-31.xsd` (+ full tracebacks)

9. does the fix also fixed this one   1.56it/s]Failed to attach schema: location=/mnt/proj_esef/data/_tmp_parse/esef_vc9puh01/Jahresfinanzbericht 2020/rathag.com/xbrl/2020/rathag-2020-12-31.xsd ... No such file or directory

10. and   1.25s/it]Failed to download http://www.apator.eu/xbrl/2023-12-31/apt-2023-12-31.xsd: HTTPConnectionPool(host='www.apator.eu', port=80): Max retries exceeded ... ConnectTimeoutError ... 'Connection to www.apator.eu timed out. (connect timeout=None)'

11. how about this one — [pasted] `Failed to download http://www.kompap.pl/xbrl/2023-12-31/kmp-2023-12-31.xsd: 403 Client Error: Forbidden` (and the 2022-12-31 filing, same error)

12. do we need to rebuild .so file or it was not touched

13. /wrap-session
