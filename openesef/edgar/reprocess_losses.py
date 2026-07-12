"""
Reprocess all filings from the loss list using subprocess workers.
Uses run_xbrl_worker() for memory isolation — each filing runs in its own process.

Usage:
    python -u -m openesef.edgar.reprocess_losses [--workers N] [--year YYYY]
"""

import sys
import os
import csv
import time
import logging
import multiprocessing as mp
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

LOSS_LIST_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'MDIS', 'data', 'dim_accounts_loss_list.csv')
EDGAR_LOCAL_PATH = '/mnt/text/edgar'


def process_one_filing(args):
    """Process a single filing via subprocess worker. Returns (adsh, year, success, error_msg)."""
    row, edgar_local_path = args
    adsh = row['adsh']
    cik = row['cik']
    year = row['year']
    index_filename = row['index_filename']
    filing_url = f"https://www.sec.gov/Archives/{index_filename}"

    try:
        from openesef.edgar.loader import run_xbrl_worker
        success = run_xbrl_worker(
            filing_url=filing_url,
            edgar_local_path=edgar_local_path,
            force_reload=True,
            memory_threshold_gb=16,
            get_dfs_int=7
        )

        if success:
            # Verify pickles exist
            tfnm = adsh
            pickle_dir = f"{edgar_local_path}/10k-bycik/{cik}/{tfnm}"
            has_fact = os.path.exists(f"{pickle_dir}/fact_df.p.gz")
            has_calc = os.path.exists(f"{pickle_dir}/calc_df.p.gz")
            has_link = os.path.exists(f"{pickle_dir}/link_df.p.gz")
            return (adsh, year, True, f"fact={'Y' if has_fact else 'N'},calc={'Y' if has_calc else 'N'},link={'Y' if has_link else 'N'}")
        else:
            return (adsh, year, False, 'worker returned failure')

    except Exception as e:
        return (adsh, year, False, str(e)[:200])


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Reprocess loss list filings')
    parser.add_argument('--workers', type=int, default=4, help='Number of parallel workers')
    parser.add_argument('--year', type=int, default=0, help='Filter to specific year (0=all)')
    parser.add_argument('--edgar', type=str, default=EDGAR_LOCAL_PATH)
    parser.add_argument('--loss-list', type=str, default=LOSS_LIST_PATH)
    parser.add_argument('--limit', type=int, default=0, help='Limit to first N filings (0=all)')
    args = parser.parse_args()

    rows = []
    with open(args.loss_list, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if args.year and row['year'] != str(args.year):
                continue
            rows.append(row)

    if args.limit:
        rows = rows[:args.limit]

    total = len(rows)
    print(f"Reprocessing {total} filings with {args.workers} workers...", flush=True)

    by_year = Counter(r['year'] for r in rows)
    for y in sorted(by_year.keys()):
        print(f"  {y}: {by_year[y]}", flush=True)

    t0 = time.time()
    work_items = [(row, args.edgar) for row in rows]

    results = []
    success_count = 0
    fail_count = 0
    success_by_year = Counter()
    fail_by_year = Counter()

    with mp.Pool(processes=args.workers) as pool:
        for i, result in enumerate(pool.imap_unordered(process_one_filing, work_items)):
            adsh, year, success, msg = result
            results.append(result)
            if success:
                success_count += 1
                success_by_year[year] += 1
            else:
                fail_count += 1
                fail_by_year[year] += 1

            if (i + 1) % 25 == 0 or (i + 1) == total:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (total - i - 1) / rate if rate > 0 else 0
                pct = 100 * success_count / (i + 1)
                print(f"[{i+1}/{total}] success={success_count} fail={fail_count} "
                      f"({pct:.0f}%) rate={rate:.2f}/s ETA={eta/60:.0f}min", flush=True)

    elapsed = time.time() - t0

    print(f"\n{'='*80}", flush=True)
    print("REPROCESSING COMPLETE", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"Total: {total}", flush=True)
    print(f"Success: {success_count} ({100*success_count/total:.1f}%)", flush=True)
    print(f"Failed: {fail_count} ({100*fail_count/total:.1f}%)", flush=True)
    print(f"Time: {elapsed/60:.1f} minutes", flush=True)
    print(flush=True)

    print("By year:", flush=True)
    print(f"  {'Year':>6} {'Success':>8} {'Fail':>8} {'Total':>8} {'Recovery%':>10}", flush=True)
    for y in sorted(set(list(success_by_year.keys()) + list(fail_by_year.keys()))):
        s = success_by_year[y]
        f = fail_by_year[y]
        t = s + f
        print(f"  {y:>6} {s:>8} {f:>8} {t:>8} {100*s/t:>9.1f}%", flush=True)

    # Save results
    out_path = os.path.join(os.path.dirname(args.loss_list), 'reprocess_results.csv')
    with open(out_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['adsh', 'year', 'success', 'details'])
        for adsh, year, success, msg in results:
            writer.writerow([adsh, year, success, msg])
    print(f"\nResults saved to: {out_path}", flush=True)


if __name__ == '__main__':
    main()
