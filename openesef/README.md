This `openesef` folder was adapted from **[XBRL-Model (`fractalexperience/xbrl/`)](https://github.com/fractalexperience/xbrl/):**, with the following changes:

1. Moved the base.pool.Pool's folder from OS's temp folder to `xbrl_schema` folder, making it reusable across multiple runs.
2. Added `util` folder to handle utility functions such as logging, memory usage, etc.
3. Added `edgar` folder to handle EDGAR-specific functions such as getting the filings.
4. Added engines.tax_pres to be able to extract the facts in relation to presentations and labels, effectively implemented the `engines.table` feature