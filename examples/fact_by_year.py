"""

This structure is much cleaner because:

1. loader.py contains the actual XBRL processing logic (get_fact_df)
2. xbrl_worker.py is just a thin wrapper that runs in a subprocess and exits
3. No need for complex JSON communication - success/failure is indicated by process exit code
4. Each filing is processed in its own process that gets cleaned up automatically
5. Memory management is handled by the OS when the process exits

#254 KPC #completed again 
python3 ~/openesef/examples/fact_by_year.py -years 2009..2014 -mw 4



#114 running 2016; can have next mw next time
python3 ~/openesef/examples/fact_by_year.py -years 2015..2019 -mw 10 # run again


#gaming pc: still running 2022
python3 openesef_repo/examples/fact_by_year.py -years 2020..2024 -mw 4


to kill:

pkill -9 -f "openesef_repo/examples/fact_by_year.py"
pkill -f "python3 *xbrl_worker.py"

Errors to deal with: 


## to update all PCs, 
### Run at mac:
rsync -avzu ~/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/ u1704may@131.234.163.252:~/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo

rsync -avzu ~/Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo/ u1704may@131.234.163.252:~/openesef


# ## run at Gaming PC

cd ~
rm -rf openesef 
git clone https://github.com/reeyarn/openesef.git

rsync -avzu ~/openesef/ /Dropbox/sciebo/WebScraping+ESEF_Paper/Research/code_fse/openesef_repo
rsync -avzu ~/openesef/ u1704may@131.234.161.218:~/openesef
rsync -avzu ~/openesef/ u1704may@131.234.161.114:~/openesef

ssh u1704may@131.234.163.254
# type password
bash

cd /tmp
git clone https://github.com/reeyarn/openesef.git
rsync -avz openesef/ ~/openesef
rm -rf openesef


"""

from openesef.edgar.edgar import get_filing_info, EG_LOCAL
#from openesef.edgar.loader import get_fact_df_wrapper
import openesef.edgar.loader as egloader
from openesef.util.util_mylogger import setup_logger
from openesef.util.ram_usage import check_memory_usage
import logging
from tqdm import tqdm
import multiprocessing as mp
from functools import partial
import gc
import datetime
import re
import pandas as pd
import argparse
logger = setup_logger("main", level=logging.INFO, log_dir="/tmp/log/")



def create_parser_get_args():
    """Argument Parser
    This function automatically creats a HELP message if run this python code in commandline with -h or --help
    And takes the argument
    
    In the default behavior of argparse, the translation from the command-line argument to the attribute name does involve replacing dashes (-) with underscores (_).
    See documentation: https://docs.python.org/3/library/argparse.html
    years = get_args_years(args)
    """
    class CustomFormatter(argparse.HelpFormatter):
        def _split_lines(self, text, width):
            lines = super()._split_lines(text, width)
            return [line + "\n" if len(line) < width - 5 else line for line in lines]
    parser = argparse.ArgumentParser(formatter_class=CustomFormatter)
    parser.add_argument("-years", "--years", type=str, help="When running, restrict to a subset of years separated by .., such as `2022..2024` ")
    parser.add_argument("-edgdir", "--edgar-root-dir", type=str, default="/mnt/text/edgar/", help = """Assign the edgar root directory. """ )
    parser.add_argument("-mw", "--max_workers", type=int, default=4, help = """Assign the number of workers to process filings in parallel. """ )
    parser.add_argument("-force", "--force_reload", action="store_true", default=False)
    parser.add_argument("-test", "--test", action="store_true")

    args = parser.parse_args()    
    for arg in vars(args):
        print(f"Argument {arg}: {getattr(args, arg)}")    
    return args    

def get_args_years(args):
    years = range(2009, 2025)
    years_arg = args.years if args.years else   ""
    logger.info(f"Value of -years: {years_arg}")
    res_yyyy_yyyy = re.search(r"^(\d\d\d\d)\.\.(\d\d\d\d)$", years_arg) 
    if re.search(r"^\d\d\d\d$", years_arg):
        years = [int(re.search(r"^\d\d\d\d$", years_arg).group(0))]
    elif res_yyyy_yyyy:    
        years = [y for y in range(int(res_yyyy_yyyy.group(1)), int(res_yyyy_yyyy.group(2))+1)]
    else:
        years = [y for y in range(1996, datetime.date.today().year)]    
    print(f"Running over years {years}")    
    return years


def process_filing(filing, edgar_local_path, force_reload=True, return_calc_df=True):
    """Process a single filing in a separate process"""
    try:
        logger.info(f"Processing {filing.url}")
        success = egloader.run_xbrl_worker(
            filing.url, 
            edgar_local_path=edgar_local_path, 
            force_reload=force_reload,
            memory_threshold_gb=16, 
            return_calc_df=True
        )
        return filing.url, success
    except Exception as e:
        logger.error(f"Error processing {filing.url}: {e}")
        return filing.url, False

def process_year(year, edgar_local_path='/mnt/text/edgar', force_reload=True, max_workers=0, return_calc_df=True):
    """Process all filings for a given year using multiprocessing"""
    egl = EG_LOCAL(edgar_local_path)
    filings = get_filing_info(forms=['10-K'], year=year, quarter=0, egl=egl)
    
    if not filings:
        logger.warning(f"No filings found for year {year}")
        return []
    
    # Create a partial function with fixed arguments
    process_func = partial(process_filing, 
                         edgar_local_path=edgar_local_path, 
                         force_reload=force_reload,
                         return_calc_df=return_calc_df)
    
    # Initialize progress bar
    pbar = tqdm(total=len(filings), desc=f"Processing {year} filings")
    results = []
    
    # Process filings in parallel with a process pool
    # Each worker will create a subprocess for each filing
    if max_workers>1:
        with mp.Pool(processes=max_workers) as pool:
            for result in pool.imap_unordered(process_func, filings):
                results.append(result)
                pbar.update()
                # check memory usage
                check_memory_usage(swap_threshold_gb=128)
    else:
        for filing in filings:
            result = process_func(filing)
            results.append(result)
            #pbar.update()
            check_memory_usage(swap_threshold_gb=128)
    pbar.close()
    
    # Summarize results
    success_count = sum(1 for _, success in results if success)
    logger.info(f"Year {year}: Processed {len(results)} filings, {success_count} successful")
    
    return results

if __name__ == "__main__":
    #main()
    args = create_parser_get_args()
    years = get_args_years(args)
    edgar_local_path = args.edgar_root_dir
    # Use fewer workers since each will spawn subprocesses
    try:
        max_workers = int(args.max_workers)
    except:
        max_workers = max(1, mp.cpu_count() // 2)  
    force_reload = args.force_reload
    return_calc_df = True
    all_results = []
    for year in years:
        logger.info(f"\nProcessing year {year}")
        results = process_year(
            year, 
            edgar_local_path=edgar_local_path,
            force_reload=force_reload,
            max_workers=max_workers,
            return_calc_df=return_calc_df
        )
        all_results.extend(results)
        
        # Create summary DataFrame
        summary_df = pd.DataFrame(results, columns=['url', 'success'])
        summary_df['year'] = year
        
        # Save year summary
        summary_file = f"/tmp/filing_summary_{year}.csv"
        summary_df.to_csv(summary_file, index=False)
        logger.info(f"Saved summary to {summary_file}")
        
        # Clear memory
        gc.collect()
    
    # Create overall summary
    final_summary = pd.DataFrame(all_results, columns=['url', 'success'])
    final_summary.to_csv("/tmp/filing_summary_all.csv", index=False)
    
    # Print final statistics
    total_filings = len(all_results)
    successful_filings = sum(1 for _, success in all_results if success)
    logger.info(f"\nFinal Summary:")
    logger.info(f"Total filings processed: {total_filings}")
    logger.info(f"Successful: {successful_filings}")
    logger.info(f"Failed: {total_filings - successful_filings}")
    logger.info(f"Success rate: {(successful_filings/total_filings)*100:.1f}%")












