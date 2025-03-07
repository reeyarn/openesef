<h1 align="center">
    <img src="https://raw.githubusercontent.com/reeyarn/openesef/refs/heads/master/markdown/esefdata.svg" alt="# Open ESEF" style="max-width: 100%; height: auto;"/>
<br>A Python Library for ESEF and XBRL Filings
<br>
<img src="https://img.shields.io/badge/Project%20Status-Under%20Development-yellow" alt="Project Status: Under Development - 70% Complete" />
<img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License: GPL v3.0" />
</h1>


This `openesef` folder was adapted from **[XBRL-Model (`fractalexperience/xbrl/`)](https://github.com/fractalexperience/xbrl/):**, with the following changes:

1. Moved the base.pool.Pool's folder from OS's temp folder to `xbrl_schema` folder, making it reusable across multiple runs.
2. Added `util` folder to handle utility functions such as logging, memory usage, etc.
3. Added `edgar` folder to handle EDGAR-specific functions such as getting the filings; adapted the code from **[SEC EDGAR Financial Reports (`farhadab/sec-edgar-financials`)](https://github.com/farhadab/sec-edgar-financials)** and now being able to get the filings from the SEC EDGAR website and extract XBRL files (.xsd, .xml).
4. Added engines.tax_pres to be able to extract the facts in relation to presentations and labels, effectively implemented the `engines.table` feature
5. Added `instance/dei.py` to be able to extract the Document Entity Information (DEI) from the XBRL files.
6. Added `filings_xbrl_org/api.py` to be able to get the ESEF filings from the XBRL filings.org website.
7. Replaced `taxonomy.concept.Concept.get_label` (previously using `util.get_label(...)` but it did not work), now it is in `taxonomy.concept.Concept.labels` dictionary. 

To be verified: `taxonomy/label.py` is not used?