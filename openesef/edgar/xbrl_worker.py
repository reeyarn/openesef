"""
Worker module for processing XBRL filings in separate processes.
This module is designed to be called as a subprocess to handle memory-intensive XBRL processing.

python3 ~/openesef/openesef/edgar/xbrl_worker.py https://www.sec.gov/Archives/edgar/data/1739940/0001739940-22-000007.txt /mnt/text/edgar true 16 true
"""

import sys
import os
from openesef.edgar.loader import get_fact_df, get_xbrl_df
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
            get_dfs_int = sys.argv[5].lower() 
        else:
            get_dfs_int = 7
        # Check initial memory state
        check_memory_usage(threshold_gb=memory_threshold_gb)
        
        # Use the existing get_fact_df function
        result = get_xbrl_df(
            filing_url=filing_url,
            edgar_local_path=edgar_local_path,
            force_reload=force_reload,
            memory_threshold_gb=memory_threshold_gb,
            get_dfs_int=int(get_dfs_int)
        )
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

        get_dfs = {"fact_df": False, "calc_df": False, "link_df": False}
        success = True
        if get_dfs_int is not None:
            # Use bitwise operations to check flags
            GET_FACT_DF = 1  # 2^0 = 1
            GET_CALC_DF = 2  # 2^1 = 2
            GET_LINK_DF = 4  # 2^2 = 4
            get_dfs = {
                "fact_df": bool(int(get_dfs_int) & GET_FACT_DF),
                "calc_df": bool(int(get_dfs_int) & GET_CALC_DF),
                "link_df": bool(int(get_dfs_int) & GET_LINK_DF)
            }
            if get_dfs["fact_df"]:
                success = success & bool( type(result["fact_df"]) == pd.DataFrame and len(result["fact_df"]) > 0 )
            if get_dfs["calc_df"]:
                success = success & bool( type(result["calc_df"]) == pd.DataFrame and len(result["calc_df"]) > 0 )
            if get_dfs["link_df"]:
                success = success & bool( type(result["link_df"]) == pd.DataFrame and len(result["link_df"]) > 0 )
            
        # Success is indicated by process exit code
        # find /tmp/log -type f -size 0 -exec rm {} \;
        if success:
            sys.exit(0)
        else:
            logger.error(f"Worker failed: {result} for {filing_url}." + " ".join(sys.argv))
            sys.exit(1)
        
    except MemoryError as me:
        logger.error(f"Memory error in worker: {me} for {filing_url} and command:" + " ".join(sys.argv))
        sys.exit(2)  # Special exit code for memory errors
    except Exception as e:
        logger.error(f"Worker failed: {e} for {filing_url}")
        sys.exit(1)


#    main() 