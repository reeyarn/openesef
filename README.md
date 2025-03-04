
# Open-ESEF: An Open Source Python Library for ESEF XBRL Filings

[![Project Status: Under Development - 66% Complete](https://img.shields.io/badge/Project%20Status-Under%20Development-yellow)](https://www.repostatus.org/#wip)
[![License: GPL v3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
<!-- Add more badges here as relevant, e.g., for documentation, tests, etc. -->

**Open-ESEF** is a Python-based, open-source project designed to handle XBRL (eXtensible Business Reporting Language) filings, specifically those adhering to the **ESEF (European Single Electronic Format)** standard. 

ESEF is the mandated digital reporting format for annual financial reports of listed companies in the European Union, established by the European Securities and Markets Authority (ESMA). Open-ESEF provides a robust toolkit for parsing, validating, and analyzing these ESEF XBRL filings.

**Funding Acknowledgment:** DFG: Funded by the Deutsche Forschungsgemeinschaft (DFG, German Research Foundation) – Collaborative Research Center (SFB/TRR) Project-ID 403041268 – TRR 266 Accounting for Transparency.

## Getting Started

### Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/reeyarn/openesef.git
    cd openesef
    ```

2.  **Install Dependencies and Package:**
    ```bash
    pip install -r requirements.txt
    pip install -e . 
    ```

3.  **Verify Installation:**
    ```python
    python -c "from openesef import base, taxonomy, instance; print('Open-ESEF installed successfully!')"
    ```

### Usage Examples

#### Example 1: Loading SEC Filings (US-GAAP iXBRL)

```python
from openesef.instance.filing_loader import load_xbrl_filing

# Load using ticker and year:
xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)

# OR Load using filing URL:
# xid, tax = load_xbrl_filing(filing_url="/Archives/edgar/data/320193/0000320193-20-000096.txt") 

if xid and tax:
    print(xid)  # Print XBRL instance info
    print(tax)  # Print taxonomy info

    # Print Document and Entity Information (DEI):
    for i, (key, value) in enumerate(xid.dei.items()):
        print(f"{i}: {key}: {value}")
```

**Explore the example with Notebooks:** [examples/apple_2020.ipynb](examples/apple_2020.ipynb)

**openesef can also extract facts from the financial statements:**

![ScreenshotTSLA](https://github.com/reeyarn/openesef/blob/master/examples/ScreenshotTSLA.png)

#### Example 2: Loading ESEF Filing (IFRS - Volkswagen 2020)

```python
# See example script:
# examples/try_vw2020.py 
```
[examples/try_vw2020.py](examples/try_vw2020.py)

## Key Features

*   **ESEF Compliance:** Specifically designed to handle XBRL filings in the ESEF format, addressing the unique folder structure and referencing conventions of ESEF reports.
*   **XBRL Taxonomy Management:**
    *   Resolves XBRL concepts, labels, and relationships.
    *   Processes XBRL linkbases (presentation, definition, calculation, label, reference).
    *   Supports taxonomy packages and efficient in-memory storage for large taxonomies.
    *   Handles references to external taxonomies like IFRS.
*   **XBRL Instance Document Processing:**
    *   Parses XBRL facts and their associated contexts (entity, period, units, decimals, dimensions).
    *   Supports dimensional data (explicit and typed dimensions, segments, scenarios).
    *   Extracts Document and Entity Information (DEI).
    *   Identifies key reporting contexts (Current/Prior, Instant/Duration).
*   **Data Modeling & Storage:**
    *   Utilizes a `Cube` class for semantic indexing of facts in a multidimensional space (dimensions: metric, entity, period, unit, custom dimensions).
    *   Optimized storage in partitioned JSON datasets within ZIP archives using SHA-1 hashing for efficient content addressing.
*   **Inline XBRL (iXBRL) Support:** Processes iXBRL documents, extracting embedded XBRL data from XHTML reports.
*   **SEC EDGAR Filing Integration (Under Review):** Includes modules for retrieving and processing filings from the U.S. SEC EDGAR system (modules are currently under review and being streamlined to focus on XBRL-related functionality).
*   **Modular Architecture:** Well-structured codebase with clear separation of concerns (base components, taxonomy logic, instance processing, engines).
*   **Logging & Debugging:** Detailed logging for taxonomy resolution and instance processing.

## Based on Open Source Projects

Open-ESEF builds upon and extends the excellent work of these open-source projects:

*   **[XBRL-Model (`fractalexperience/xbrl/`)](https://github.com/fractalexperience/xbrl/):** Provides the foundation for XBRL parsing, taxonomy handling, and data modeling. Open-ESEF adapts and extends this library to handle ESEF-specific requirements.
*   **[SEC EDGAR Financial Reports (`farhadab/sec-edgar-financials`)](https://github.com/farhadab/sec-edgar-financials):**  Provides code for interacting with the SEC EDGAR system (modules are currently under review and being streamlined).
*   **[pyXBRL (`ifanchu/pyXBRL`)](https://github.com/ifanchu/pyXBRL):**  (used the code for the DEI part, aka the document and entity information, such as the current fiscal period, fiscal year end, etc.).
*   **[ESEF.jl (Julia)](https://github.com/trr266/ESEF.jl):** (used their hint to use the filings.xbrl.org API to get the ESEF filings).

## Other Related Projects

*   **[gepsio (.Net)](https://github.com/JeffFerguson/gepsio):** .Net library for XBRL and ESEF.
*   **[parse-xbrl (JavaScript)](https://github.com/emilycoco/parse-xbrl):** JavaScript XBRL parser.
*   **[altova/sec-xbrl/tree/master (Python, Altova)](https://github.com/altova/sec-xbrl/tree/master):** Altova's Python SEC XBRL tools.
*   **[secdatabase/SEC-XBRL-Financial-Statement-Dataset](https://github.com/secdatabase/SEC-XBRL-Financial-Statement-Dataset) ([https://www.secdatabase.com/](https://www.secdatabase.com/)):** SEC XBRL financial statement dataset.
*   **[altova/sec-xbrl/ (Python)](https://github.com/altova/sec-xbrl/):** Another Altova Python XBRL repo.
*   **[DataQualityCommittee/dqc_us_rules/ (xbrl.us/dqc aka XBRL-US Data Quality Committee Rules)](https://github.com/DataQualityCommittee/dqc_us_rules/):** XBRL-US Data Quality Committee Rules.
*   **[steffen-zou/Extract-financial-data-from-XBRL/](https://github.com/steffen-zou/Extract-financial-data-from-XBRL/):** Python XBRL data extraction.


## Project Architecture

[**Detailed Architecture Overview (Coming Soon)**] - *This section will be expanded to provide a more in-depth look at the Open-ESEF architecture.*

**Key Components:**

*   **`base`:** Core modules providing fundamental classes and utilities (e.g., `pool`, `resolver`, `ebase`, `fbase`).
*   **`taxonomy`:** Modules for handling XBRL taxonomies (`taxonomy`, `schema`, `linkbase`, `tpack`).
*   **`instance`:** Modules for processing XBRL instance documents (`instance`, `fact`, `context`, `unit`, `dei`, `filing_loader`).
*   **`edgar` (Under Review):** Modules for SEC EDGAR filing retrieval (currently being streamlined).
*   **`engines` (To Explore):** Modules for reporting and data analysis (functionality to be documented).
*   **`util`:** Utility functions and helper classes.

**Data Flow (Simplified):**

1.  **Input:** XBRL/ESEF instance documents and taxonomy files.
2.  **Resolution:** Taxonomies and schemas are resolved and cached.
3.  **Parsing:** Instance documents are parsed, facts and contexts extracted.
4.  **Modeling:** Data is modeled using `Taxonomy`, `Instance`, and `Cube` classes.
5.  **Output:** Processed data can be accessed programmatically or serialized for storage/analysis.

**Technical Highlights:**

*   **LXML for XML Processing:**  Efficient XML parsing and XLink resolution.
*   **SHA-1 Hashing:**  Content addressing for optimized data storage.
*   **Memory File System:**  Uses `fs.memory` for in-memory file handling and caching.
*   **Modular Design:**  Encapsulated components for maintainability and extensibility.

**Standards Compliance:**

*   XBRL 2.1
*   XBRL Dimensions 1.0
*   ESEF Reporting Manual

## Recent Updates

*   **0.2.0 Latest**
    @reeyarn reeyarn released this 2 minutes ago
    alpha-two
    f28c670
    Integrated the code from farhadab/sec-edgar-financials; Using memfs to load XBRL files from inside EDGAR's full-text file without writing to tempdir.


## To-Do & Roadmap

*   **Complete Documentation:** Expand documentation for all modules and classes.
*   **Enhance Validation:** Implement more comprehensive ESEF validation rules.
*   **Explore Reporting Engines:** Document and enhance reporting capabilities in the `engines` folder.
*   **Refine SEC EDGAR Modules:** Streamline and focus `edgar` modules on XBRL-related aspects.
*   **Add Unit Tests:** Improve code quality and stability with unit tests.
*   **Community Contributions:** Welcome contributions, feedback, and issue reports!

## Author Information

*   **Author:** Reeyarn Zhiyang Li
*   **Email:** reeyarn+github.openesef@gmail.com
*   **Website:** [https://reeyarn.li](https://reeyarn.li)

---

**Open-ESEF** is under active development. Stay tuned for updates and new features as the project progresses!

