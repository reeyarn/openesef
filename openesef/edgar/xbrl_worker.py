"""
Worker module for processing XBRL filings in separate processes.
This module is designed to be called as a subprocess to handle memory-intensive XBRL processing.
"""

import sys
from openesef.edgar.loader import get_fact_df
from openesef.util.util_mylogger import setup_logger
import logging
from openesef.util.ram_usage import check_memory_usage
#import traceback
import os
import datetime
import re
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

def main():
    """
    Process a single filing and exit.
    Expects arguments: filing_url edgar_local_path force_reload memory_threshold_gb
    """
    try:
        filing_url = sys.argv[1]
        edgar_local_path = sys.argv[2]
        force_reload = sys.argv[3].lower() == 'true'
        memory_threshold_gb = int(sys.argv[4])
        
        # Check initial memory state
        check_memory_usage(threshold_gb=memory_threshold_gb)
        
        # Use the existing get_fact_df function
        fact_df = get_fact_df(
            filing_url=filing_url,
            edgar_local_path=edgar_local_path,
            force_reload=force_reload,
            memory_threshold_gb=memory_threshold_gb
        )
        
        # Check final memory state
        check_memory_usage(threshold_gb=memory_threshold_gb)
        
        
        
        # if success, remove the log file
        res_url = re.search(r"Archives/edgar/data/(\d+)/(\d+(?:-\d*)*)\D", filing_url)
        if res_url:
            fcik = res_url.group(1) 
            tfnm = res_url.group(2)
            pid = f"{fcik}_{tfnm}"
        else:
            pid = os.getpid()
            
        log_filename = os.path.join("/tmp/log/", f"log_xbrl_worker_{datetime.datetime.now().strftime('%Y%m%d')}_p{pid}.log")        
        os.remove(log_filename)
        # Success is indicated by process exit code
        sys.exit(0 if fact_df is not None else 1)
        
    except MemoryError as me:
        logger.error(f"Memory error in worker: {me} for {filing_url}")
        sys.exit(2)  # Special exit code for memory errors
    except Exception as e:
        logger.error(f"Worker failed: {e} for {filing_url}")
        sys.exit(1)

if __name__ == "__main__":
    main() 