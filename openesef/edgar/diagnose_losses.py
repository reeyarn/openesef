"""
Diagnostic script for mission-critical EDGAR pickle generation failures.
Reads the loss list from MDIS (read-only) and inspects each failing filing
to categorize the failure mode.

Usage:
    python -m openesef.edgar.diagnose_losses [--sample N] [--year YYYY]
"""

import sys
import os
import re
import csv
import logging
import traceback
from collections import Counter

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from openesef.util.util_mylogger import setup_logger
from openesef.edgar.edgar import EG_LOCAL
from openesef.edgar.filing import Filing

logger = setup_logger("diagnose", logging.INFO, log_dir="/tmp/", full_format=True, pid="diagnose")


LOSS_LIST_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'MDIS', 'data', 'dim_accounts_loss_list.csv')
EDGAR_LOCAL_PATH = '/mnt/text/edgar'


def diagnose_filing(row, edgar_local_path=EDGAR_LOCAL_PATH):
    """Diagnose a single filing from the loss list. Returns a dict with diagnosis."""

    cik = row['cik']
    adsh = row['adsh']
    index_filename = row['index_filename']
    year = row['year']
    company = row['CompanyName']

    # Construct filing URL
    filing_url = f"https://www.sec.gov/Archives/{index_filename}"

    result = {
        'cik': cik,
        'adsh': adsh,
        'year': year,
        'company': company,
        'filing_url': filing_url,
        'category': 'unknown',
        'details': '',
    }

    # Check if pickles already exist (maybe fixed in a rerun)
    tfnm = adsh  # adsh IS the tfnm
    pickle_dir = f"{edgar_local_path}/10k-bycik/{cik}/{tfnm}"
    fact_exists = os.path.exists(f"{pickle_dir}/fact_df.p.gz")
    calc_exists = os.path.exists(f"{pickle_dir}/calc_df.p.gz")
    link_exists = os.path.exists(f"{pickle_dir}/link_df.p.gz")
    result['pickles_exist'] = f"fact={fact_exists}, calc={calc_exists}, link={link_exists}"

    if fact_exists and calc_exists:
        result['category'] = 'already_fixed'
        result['details'] = 'Pickle files exist — may have been fixed in a rerun'
        return result

    # Step 1: Create Filing object and inspect documents
    try:
        egl = EG_LOCAL(edgar_local_path)
        filing = Filing(url=filing_url, egl=egl)
    except Exception as e:
        result['category'] = 'filing_load_error'
        result['details'] = f"Cannot load filing: {e}"
        return result

    # Step 2: Inspect all documents — types and filenames
    doc_types = []
    xml_xsd_docs = []
    for fname, doc in filing.documents.items():
        doc_types.append((fname, doc.type))
        if fname.lower().endswith('.xml') or fname.lower().endswith('.xsd'):
            xml_xsd_docs.append((fname, doc.type))

    result['total_documents'] = len(filing.documents)
    result['xml_xsd_documents'] = str(xml_xsd_docs)

    # Step 3: Check get_xbrl_files() result
    xbrl_files = filing.xbrl_files  # Already computed in __init__
    result['xbrl_files'] = str(xbrl_files)

    if not xbrl_files:
        # No XBRL files found — check WHY
        if not xml_xsd_docs:
            result['category'] = 'no_xml_documents'
            result['details'] = f"Filing has 0 XML/XSD documents. Total docs: {len(filing.documents)}. Types: {[t for _, t in doc_types[:10]]}"
        else:
            result['category'] = 'doc_type_mismatch'
            result['details'] = f"Has {len(xml_xsd_docs)} XML/XSD docs but get_xbrl_files() returned empty. Doc types: {xml_xsd_docs}"
        return result

    has_sch = 'sch' in xbrl_files
    has_pre = 'pre' in xbrl_files
    has_cal = 'cal' in xbrl_files
    has_xml = 'xml' in xbrl_files
    result['has_files'] = f"xml={has_xml}, sch={has_sch}, pre={has_pre}, cal={has_cal}"

    if not has_xml:
        result['category'] = 'no_instance_xml'
        result['details'] = 'get_xbrl_files() found files but no instance XML'
        return result

    # Step 4: Try loading taxonomy to count linkbases and locators
    try:
        import fs
        from io import BytesIO
        from lxml import etree as lxml_etree
        from openesef.base.pool import Pool
        from openesef.taxonomy.taxonomy import Taxonomy
        from openesef.instance.instance import Instance

        memfs = fs.open_fs('mem://')

        entry_points = []
        for key, filename in xbrl_files.items():
            content = filing.documents[filename].doc_text.data
            content = list(content.values())[0] if isinstance(content, dict) else content
            with memfs.open(filename, 'w') as f:
                f.write(content)
            if "xml" in filename:
                entry_points.append(f"mem://{filename}")

        result['entry_points'] = str(entry_points)

        data_pool = Pool(max_error=32, esef_filing_root="mem://", memfs=memfs)
        tax = Taxonomy(
            entry_points=entry_points,
            container_pool=data_pool,
            esef_filing_root="mem://",
            memfs=memfs
        )

        n_schemas = len(tax.schemas)
        n_linkbases = len(tax.linkbases)
        n_locators = len(tax.locators)
        n_base_sets = len(tax.base_sets)
        n_concepts = len(tax.concepts_by_qname)

        result['taxonomy'] = f"schemas={n_schemas}, linkbases={n_linkbases}, locators={n_locators}, base_sets={n_base_sets}, concepts={n_concepts}"

        # Check linkbase details
        lb_details = []
        for href, lb in tax.linkbases.items():
            n_links = len(getattr(lb, 'links', []))
            total_locs = sum(len(xl.locators_by_href) for xl in lb.links) if hasattr(lb, 'links') else 0
            lb_details.append(f"{os.path.basename(href)}: {n_links} links, {total_locs} locators")
        result['linkbase_details'] = '; '.join(lb_details) if lb_details else 'none'

        # Check presentation networks
        pres_networks = [k for k in tax.base_sets.keys()
                        if isinstance(k, tuple) and len(k) >= 1 and 'presentation' in str(k[0]).lower()]
        result['presentation_networks'] = len(pres_networks)

        if n_linkbases == 0:
            result['category'] = 'no_linkbases_loaded'
            result['details'] = f"Taxonomy loaded {n_schemas} schemas, {n_concepts} concepts, but 0 linkbases"
        elif n_locators == 0:
            result['category'] = '0_locators'
            result['details'] = f"Taxonomy has {n_linkbases} linkbases but 0 locators. Linkbases: {result['linkbase_details']}"
        elif len(pres_networks) == 0:
            result['category'] = '0_presentation_networks'
            result['details'] = f"Has {n_locators} locators, {n_base_sets} base_sets, but 0 presentation networks"
        else:
            # Taxonomy looks OK — try ins_facts
            try:
                from openesef.engines.tax_pres_py import TaxonomyPresentation
                t_pres = TaxonomyPresentation(tax)
                if t_pres.concept_df is None or t_pres.concept_df.empty:
                    result['category'] = 'empty_concept_df'
                    result['details'] = f"TaxonomyPresentation found {len(pres_networks)} pres networks but concept_df is empty"
                else:
                    result['category'] = 'taxonomy_ok_other_error'
                    result['details'] = f"Taxonomy OK ({len(pres_networks)} pres networks, {len(t_pres.concept_dict)} concepts) — error is downstream"
            except Exception as e:
                result['category'] = 'tax_pres_crash'
                result['details'] = f"TaxonomyPresentation crashed: {e}"

        memfs.close()

    except Exception as e:
        result['category'] = 'taxonomy_load_error'
        result['details'] = f"Error loading taxonomy: {e}\n{traceback.format_exc()}"

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Diagnose EDGAR pickle generation failures')
    parser.add_argument('--sample', type=int, default=20, help='Number of filings to sample')
    parser.add_argument('--year', type=int, default=0, help='Filter to specific fiscal year (0=all)')
    parser.add_argument('--edgar', type=str, default=EDGAR_LOCAL_PATH, help='EDGAR local path')
    parser.add_argument('--loss-list', type=str, default=LOSS_LIST_PATH, help='Path to loss list CSV')
    args = parser.parse_args()

    # Read loss list
    loss_list_path = args.loss_list
    if not os.path.exists(loss_list_path):
        # Try relative to script
        loss_list_path = os.path.abspath(loss_list_path)

    print(f"Reading loss list from: {loss_list_path}")
    rows = []
    with open(loss_list_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if args.year and row['year'] != str(args.year):
                continue
            rows.append(row)

    print(f"Total rows: {len(rows)}")

    # Stratified sample
    by_year = {}
    for row in rows:
        y = row['year']
        by_year.setdefault(y, []).append(row)

    print(f"\nDistribution by year:")
    for y in sorted(by_year.keys()):
        print(f"  {y}: {len(by_year[y])} filings")

    # Sample: prioritize 2023-2024
    sample = []
    sample_per_year = max(2, args.sample // len(by_year)) if by_year else args.sample
    for y in sorted(by_year.keys(), reverse=True):  # newest first
        n = min(sample_per_year, len(by_year[y]))
        if y in ('2023', '2024'):
            n = min(max(5, sample_per_year), len(by_year[y]))
        sample.extend(by_year[y][:n])
        if len(sample) >= args.sample:
            break

    sample = sample[:args.sample]
    print(f"\nDiagnosing {len(sample)} filings...\n")
    print("=" * 100)

    categories = Counter()
    results = []

    for i, row in enumerate(sample):
        print(f"\n[{i+1}/{len(sample)}] CIK={row['cik']} | ADSH={row['adsh']} | Year={row['year']} | {row['CompanyName']}")
        print(f"  URL: https://www.sec.gov/Archives/{row['index_filename']}")

        result = diagnose_filing(row, edgar_local_path=args.edgar)
        results.append(result)
        categories[result['category']] += 1

        print(f"  Category: {result['category']}")
        print(f"  Pickles: {result.get('pickles_exist', 'N/A')}")
        print(f"  XBRL files: {result.get('xbrl_files', 'N/A')}")
        print(f"  Has files: {result.get('has_files', 'N/A')}")
        print(f"  Taxonomy: {result.get('taxonomy', 'N/A')}")
        print(f"  Linkbase details: {result.get('linkbase_details', 'N/A')}")
        print(f"  Pres networks: {result.get('presentation_networks', 'N/A')}")
        print(f"  Details: {result['details']}")
        print("-" * 100)

    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    for cat, count in categories.most_common():
        print(f"  {cat}: {count}")
    print(f"\n  Total diagnosed: {len(results)}")

    return results


if __name__ == '__main__':
    main()
