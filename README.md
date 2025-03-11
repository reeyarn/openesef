<!--# Open ESEF: A Python Library for ESEF and XBRL Filings-->
<h1 align="center">
    <img src="https://raw.githubusercontent.com/reeyarn/openesef/refs/heads/master/markdown/esefdata.svg" alt="# Open ESEF" style="max-width: 100%; height: auto;"/>
<br>A Python Library for ESEF and XBRL Filings
<br>
<img src="https://img.shields.io/badge/Project%20Status-Under%20Development-yellow" alt="Project Status: Under Development - 70% Complete" />
<img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License: GPL v3.0" />
</h1>

**Open-ESEF** is a Python-based, open-source project designed to handle XBRL (eXtensible Business Reporting Language) filings, specifically those adhering to the **ESEF (European Single Electronic Format)** standard. 

ESEF is the mandated digital reporting format for annual financial reports of listed companies in the European Union, established by the European Securities and Markets Authority (ESMA). Open-ESEF provides a robust toolkit for parsing, validating, and analyzing these ESEF XBRL filings.

**Funding Acknowledgment (DFG):** Funded by the Deutsche Forschungsgemeinschaft (DFG, German Research Foundation) – Collaborative Research Center (SFB/TRR) Project-ID 403041268 – _TRR 266 Accounting for Transparency_.

**Open-ESEF** is under active development. Stay tuned for updates and new features as the project progresses!

## Getting Started

### Install the stable release using pip

To install the latest stable version:


```bash
pip install openesef
```

### Alternatively: Installing the latest version with git

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/reeyarn/openesef.git
    cd openesef
    ```

2.  **Install Dependencies and Build Package:**
    ```bash
    # Install Cython first
    pip install cython

    # Install the package in development mode with Cython compilation
    pip install -e . 
    ```

Note: The package will automatically compile the Cython extensions during installation. If you modify any .pyx files, you'll need to reinstall the package using `pip install -e .` again.

3.  **Verify Installation:**
    ```python
    python -c "from openesef import base, taxonomy, instance; import openesef.engines.tax_pres as oetp; print('Open-ESEF installed successfully!')"
    ```


### Usage Examples

#### Example 1: Loading SEC Filings (US-GAAP iXBRL)

**Explore the Example and output with Notebooks:** [examples/apple_2020.ipynb](examples/apple_2020.ipynb)

* Load XBRL filing using ticker and year 
    ```python
    from openesef.edgar.loader import load_xbrl_filing
    from openesef.engines.tax_pres import TaxonomyPresentation

    # Load XBRL filing using ticker and year
    xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)

    # OR Load using filing URL:
    # xid, tax = load_xbrl_filing(filing_url="/Archives/edgar/data/320193/0000320193-20-000096.txt") 
    ```


* Create presentation object to analyze statements and concepts

    ```python
    t_pres = TaxonomyPresentation(tax)

    # Print statement names
    print("\nFinancial Statements:")
    for statement in t_pres.statement_dimensions.keys():
        print(f"- {statement}")
    ```

* Get concepts from Statement of Operations

    ```python
    print("\nConcepts in Statement of Operations:")
    statement_concepts = t_pres.statement_concepts.get('CONSOLIDATEDSTATEMENTSOFOPERATIONS', [])
    concepts_statement_of_operations = []
    for concept in statement_concepts:
        concepts_statement_of_operations.append(concept['concept_qname'])
        print(f"Statement: {concept['statement_name']}")
        print(f"Concept: {concept['concept_qname']}")
        print(f"Label: {concept['label']}")        
            
    ```

* Print fact values for Statement of Operations concepts

    ```python

    print("\nFact Values:")
    for key, fact in xid.xbrl.facts.items():
        concept_qname = str(fact.qname)
        context = xid.xbrl.contexts[fact.context_ref]
        if concept_qname in concepts_statement_of_operations: 
            print(f"{concept_qname:<90} Value: {fact.value:<15} ")    
          
    ```




<!--![ScreenshotTSLA](https://github.com/reeyarn/openesef/blob/master/examples/ScreenshotTSLA.png)-->

#### Example 2: Loading ESEF Filing (IFRS - Volkswagen 2020)

In this forked repository, I began by adapting the code from the `fractalexperience/xbrl/` package to facilitate its compatibility with ESEF. 

The issue in that repository was that, unlike  US-SEC-EDGAR, ESEF files adhere to a folder structure. Consequently, the schema references in ESEF files are relative to the instance file rather than the taxonomy folder, and `fractalexperience/xbrl/` package did not handle this out of the box.  Using SAP SE 2022 ESEF filing as an example, the ESEF filing root folder contains the following folders and files:

```
  📦 sap-2022-12-31-DE
  ├── 📦 META-INF
  │   ├── 📄 catalog.xml
  │   └── 📄 taxonomyPackage.xml
  ├── 📦 reports
  │   └── 📄 sap-2022-12-31-DE.xhtml
  └── 📦 www.sap.com
      ├── 📄 sap-2022-12-31.xsd
      ├── 📄 sap-2022-12-31_cal.xml
      ├── 📄 sap-2022-12-31_def.xml
      ├── 📄 sap-2022-12-31_lab-de.xml
      ├── 📄 sap-2022-12-31_lab-en.xml
      └── 📄 sap-2022-12-31_pre.xml
```

I have tried to modify the code to handle ESEF by adding the `esef_filing_root` parameter and passing it around.

**Explore the example with code:** [examples/try_vw2020.py](examples/try_vw2020.py) 


## Attribution

### ESEF Standard Acknowledgment
This project supports the **European Single Electronic Format (ESEF)**, established by the **European Securities and Markets Authority (ESMA)** as the mandated digital reporting standard for annual financial reports of listed companies in the European Union. The ESEF specifications and guidelines are sourced from ESMA’s official publications and are adhered to in this implementation. For more information, visit [esma.europa.eu](https://www.esma.europa.eu).

### IFRS Taxonomy Acknowledgment
This project leverages the **IFRS Taxonomy**, developed and maintained by the **IFRS Foundation**, to process XBRL filings based on International Financial Reporting Standards (IFRS). The taxonomy files are sourced from the IFRS Foundation’s official repository and are used in accordance with their terms of use. For more information, visit [ifrs.org](https://www.ifrs.org).

### US GAAP Taxonomy Acknowledgment

This project utilizes the US GAAP Financial Reporting Taxonomy, developed and maintained by the **Financial Accounting Standards Board (FASB)** and **XBRL US**. The taxonomy files (e.g., `us-gaap-YYYY-MM-DD.xsd`) are sourced from xbrl.fasb.org and are used in compliance with their terms of use. For more information, visit [fasb.org](https://fasb.org) and [xbrl.us](https://xbrl.us).

### Disclaimer
The use of these standards and taxonomies is intended to support educational and research purposes in alignment with the open-source goals of this project. If any use herein is found to infringe upon the rights of the FASB, XBRL US, ESMA, or the IFRS Foundation, please contact the author at [reeyarn+github.openesef@gmail.com](mailto:reeyarn+github.openesef@gmail.com), and I will promptly remove or adjust the offending content to address any concerns.

## Based on Open Source Projects

Open-ESEF builds upon and extends the excellent work of these open-source projects:

*   **[XBRL-Model (`fractalexperience/xbrl/`)](https://github.com/fractalexperience/xbrl/):** Provides the foundation for XBRL parsing, taxonomy handling, and data modeling. Open-ESEF adapts and extends this library to handle ESEF-specific requirements.
*   **[SEC EDGAR Financial Reports (`farhadab/sec-edgar-financials`)](https://github.com/farhadab/sec-edgar-financials):**  Provides code for interacting with the SEC EDGAR system (modules are currently under review and being streamlined).
*   **[pyXBRL (`ifanchu/pyXBRL`)](https://github.com/ifanchu/pyXBRL):**  (used the code for the DEI part, aka the document and entity information, such as the current fiscal period, fiscal year end, etc.).
*   **[ESEF.jl (Julia)](https://github.com/trr266/ESEF.jl):** (used their hint to use the filings.xbrl.org API to get the ESEF filings).

## Other Related Projects
*   **[BrelLibrary/brel](https://github.com/BrelLibrary/brel)** a Python library  for reading and analyzing financial reports developped by Robin Schmidiger (a master student at ETH Zurich Department of Computer Science System Groups, supervised by Prof. Gustavo Alonso and Dr. Ghislain Fourny); see his [master thesis](https://github.com/BrelLibrary/brel/blob/main/docs/thesis_latex/thesis.pdf)
*   **[gepsio (.Net)](https://github.com/JeffFerguson/gepsio):** .Net library for XBRL and ESEF.
*   **[parse-xbrl (JavaScript)](https://github.com/emilycoco/parse-xbrl):** JavaScript XBRL parser.
*   **[altova/sec-xbrl/tree/master (Python, Altova)](https://github.com/altova/sec-xbrl/tree/master):** Altova's Python SEC XBRL tools.
*   **[secdatabase/SEC-XBRL-Financial-Statement-Dataset](https://github.com/secdatabase/SEC-XBRL-Financial-Statement-Dataset) ([https://www.secdatabase.com/](https://www.secdatabase.com/)):** SEC XBRL financial statement dataset.
*   **[altova/sec-xbrl/ (Python)](https://github.com/altova/sec-xbrl/):** Another Altova Python XBRL repo.
*   **[DataQualityCommittee/dqc_us_rules/ (xbrl.us/dqc aka XBRL-US Data Quality Committee Rules)](https://github.com/DataQualityCommittee/dqc_us_rules/):** XBRL-US Data Quality Committee Rules.
*   **[steffen-zou/Extract-financial-data-from-XBRL/](https://github.com/steffen-zou/Extract-financial-data-from-XBRL/):** Python XBRL data extraction.


## Key Features

*   **ESEF Compliance:** Specifically designed to handle XBRL filings in the ESEF format, addressing the unique folder structure and referencing conventions of ESEF reports.
*   **XBRL Taxonomy Management:**
    *   Resolves XBRL concepts, labels, and relationships.
    *   Processes XBRL linkbases (presentation, definition, calculation, label, reference).
    *   Supports taxonomy packages and efficient in-memory storage for large taxonomies.
    *   Handles references to external taxonomies like US-GAAP, IFRS, etc.

*   **XBRL Instance Document Processing:**
    *   Parses XBRL facts and their associated contexts (entity, period, units, decimals, dimensions).
    *   Supports dimensional data (explicit and typed dimensions, segments, scenarios).
    *   Extracts Document and Entity Information (DEI).
    *   Identifies key reporting contexts (Current/Prior, Instant/Duration).

*   **Data Modeling & Storage:**
    *   Utilizes a `Cube` class for semantic indexing of facts in a multidimensional space (dimensions: metric, entity, period, unit, custom dimensions).
    *   Optimized storage in partitioned JSON datasets within ZIP archives using SHA-1 hashing for efficient content addressing.

*   **Inline XBRL (iXBRL) Support:** Processes iXBRL documents, extracting embedded XBRL data from XHTML reports.

*   **SEC EDGAR Integration:**
    *   Direct access to SEC EDGAR filings using company tickers
    *   Real-time ticker to CIK mapping using SEC's company tickers API `https://www.sec.gov/files/company_tickers.json`; added `edgar.stock.update_symbols_data()` to update the symbols data file.  
    *   Automatic handling of filing downloads and XBRL extraction.

*   **Modular Architecture:** Well-structured codebase with clear separation of concerns (base components, taxonomy logic, instance processing, engines).
*   
*   **Logging & Debugging:** Detailed logging for taxonomy resolution and instance processing.


## Project Architecture

[**Detailed Architecture Overview (Coming Soon)**] - *This section will be expanded to provide a more in-depth look at the Open-ESEF architecture.*

**Key Components:**

*   **`base`:** Core modules providing fundamental classes and utilities (e.g., `pool`, `resolver`, `ebase`, `fbase`).
*   **`taxonomy`:** Modules for handling XBRL taxonomies (`taxonomy`, `schema`, `linkbase`, `tpack`).
*   **`instance`:** Modules for processing XBRL instance documents (`instance`, `fact`, `context`, `unit`, `dei`, `filing_loader`).
*   **`engines`:** Modules for reporting and data analysis (functionality to be documented).
*   **`edgar`:** Modules for SEC EDGAR filing retrieval (currently being streamlined).
*   **`filings_xbrl_org`:** Interacting with `https://filings.xbrl.org/` to get the ESEF filings.
*   **`util`:** Utility functions such as `util_mylogger.setup_logger()` .

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
*   **0.3.8**
    *   `engines/tax_pres.py` 
        - Used Cython to this file
        - Enhanced taxonomy presentation processing
        - Fixed calculation linkbase processing errors
        - Improved memory management for large filings
        - Optimized fact extraction for disclosures
        - Added better error handling for label links
        - Enhanced logging and memory usage tracking
    *   `engines/ins_facts.py` 
        - Moved `fact_df = ins_facts(xid, tax)` to 
    *  `edgar/loader.py` added `get_xbrl_df()` to replace `get_fact_df()`
*   **0.3.7**
    *   Taxonomy now processes calculation networks
    *   Added `engines.tax_pres.tax_calc_df()` to get the calculation network dataframe
        
*   **0.3.5**
    *   Improved `engines.tax_pres` by avoiding double for loop for disclosure only facts

*   **0.3.1**
    *   Added `util.ram_usage.check_memory_usage()` to check the memory usage

*   **0.3.0**
    *   Enhanced taxonomy presentation processing with new `TaxonomyPresentation` class:
        - Intelligent statement detection and concept organization
        - Automated extraction of financial statement structures
        - Improved dimension and segment validation
        - Support for both US-GAAP and IFRS taxonomies
    *   Integrated SEC EDGAR functionality with memfs for efficient XBRL extraction
    *   Added statement-specific concept mapping and validation
    *   Improved fact extraction with dimensional context support



## Author Information

*   **Author:** Reeyarn Zhiyang Li
*   **Email:** reeyarn+github.openesef@gmail.com
*   **Website:** [https://reeyarn.li](https://reeyarn.li)



