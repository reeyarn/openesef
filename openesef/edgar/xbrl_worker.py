"""
Worker module for processing XBRL filings in separate processes.
This module is designed to be called as a subprocess to handle memory-intensive XBRL processing.

https://www.sec.gov/Archives/edgar/data/1739940/0001739940-22-000007.txt 
"""

import sys
import os
from openesef.edgar.loader import get_fact_df
from openesef.util.util_mylogger import setup_logger
import logging
from openesef.util.ram_usage import check_memory_usage
#import traceback
import datetime
import re
import pandas as pd

# Set up environment before any other imports
if len(sys.argv) > 2:
    os.environ['EDGAR_ROOT_DIR'] = sys.argv[2]  # Set environment variable for edgar root dir


if __name__=="__main__":
    pid = os.getpid()
    filing_url = sys.argv[1]
    res_url = re.search(r"Archives/edgar/data/(\d+)/(\d+(?:-\d*)*)\D", filing_url)
    if res_url:
        fcik = res_url.group(1) 
        tfnm = res_url.group(2)
        pid = f"{fcik}_{tfnm}"

    logger = setup_logger("xbrl_worker", level=logging.DEBUG, log_dir="/tmp/log/", pid=pid)
else:
    logger = logging.getLogger("main.openesf.edgar.xbrl_worker")

if __name__ == "__main__":
    """
    Process a single filing and exit.
    Expects arguments: filing_url edgar_local_path force_reload memory_threshold_gb
    """
    try:
        filing_url = sys.argv[1]
        if len(sys.argv) > 2:   
            edgar_local_path = sys.argv[2]
        else:
            edgar_local_path = "/text/edgar"
        if len(sys.argv) > 3:
            force_reload = sys.argv[3].lower() == 'true' 
        else:
            force_reload = False
        if len(sys.argv) > 4:
            memory_threshold_gb = int(sys.argv[4]) 
        else:
            memory_threshold_gb = 16
        if len(sys.argv) > 5:
            return_calc_df = sys.argv[5].lower() == 'true' 
        else:
            return_calc_df = False
        # Check initial memory state
        check_memory_usage(threshold_gb=memory_threshold_gb)
        
        # Use the existing get_fact_df function
        result = get_fact_df(
            filing_url=filing_url,
            edgar_local_path=edgar_local_path,
            force_reload=force_reload,
            memory_threshold_gb=memory_threshold_gb,
            return_calc_df=return_calc_df
        )
        if return_calc_df:
            calc_df = result[1]
            fact_df = result[0]
        else:
            fact_df = result
        # Check final memory state
        check_memory_usage(threshold_gb=memory_threshold_gb)
        
        # If success, check if log file exists and remove it if it has zero size
        res_url = re.search(r"Archives/edgar/data/(\d+)/(\d+(?:-\d*)*)\D", filing_url)
        if res_url:
            fcik = res_url.group(1) 
            tfnm = res_url.group(2)
            pid = f"{fcik}_{tfnm}"
        else:
            pid = os.getpid()
            
        log_filename = os.path.join("/tmp/log/", f"log_xbrl_worker_{datetime.datetime.now().strftime('%Y%m%d')}_p{pid}.log")        
        if os.path.exists(log_filename) and os.path.getsize(log_filename) == 0:
            os.remove(log_filename)
        # Success is indicated by process exit code
        # find /tmp/log -type f -size 0 -exec rm {} \;
        sys.exit(0 if type(fact_df) == pd.DataFrame and len(fact_df) > 0 else 1)
        
    except MemoryError as me:
        logger.error(f"Memory error in worker: {me} for {filing_url} and command:" + " ".join(sys.argv))
        sys.exit(2)  # Special exit code for memory errors
    except Exception as e:
        logger.error(f"Worker failed: {e} for {filing_url}")
        sys.exit(1)


#    main() 