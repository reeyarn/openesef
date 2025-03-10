"""
Worker module for processing XBRL filings in separate processes.
This module is designed to be called as a subprocess to handle memory-intensive XBRL processing.

python3 ~/openesef/openesef/edgar/xbrl_worker.py https://www.sec.gov/Archives/edgar/data/1739940/0001739940-22-000007.txt /mnt/text/edgar true 16 true

Check timeout issue
 00:00:02 /usr/bin/python3 /home/u1704may/openesef/openesef/edgar/xbrl_worker.py https://www.sec.gov/Archives/edgar/data/350797/0001144204-10-067744.txt /mnt/text/edgar/ True 16 7
u1704may 2387812 2091764  0 08:40 pts/4    00:00:02 /usr/bin/python3 /home/u1704may/openesef/openesef/edgar/xbrl_worker.py https://www.sec.gov/Archives/edgar/data/731802/0000950123-10-105040.txt /mnt/text/edgar/ True 16 7
u1704may 2388570 2091761  0 08:40 pts/4    00:00:02 /usr/bin/python3 /home/u1704may/openesef/openesef/edgar/xbrl_worker.py https://www.sec.gov/Archives/edgar/data/78460/0000950123-10-116014.txt /mnt/text/edgar/ True 16 7
u1704may 2388867 2091763  0 08:41 pts/4    00:00:02 /usr/bin/python3 /home/u1704may/openesef/openesef/edgar/xbrl_worker.py https://www.sec.gov/Archives/edgar/data/794172/0000950123-10-109251.txt /mnt/text/edgar/ True 16 7s
"""

import sys
import os
from openesef.edgar.loader import get_xbrl_df
from openesef.util.util_mylogger import setup_logger
import logging
#from openesef.util.ram_usage import check_memory_usage
from openesef.util.ram_usage import  memory_check #timeout,
#import traceback
import datetime
import re
import pandas as pd
import warnings
import time
# Specifically ignore only SettingWithCopyWarning
warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)

#import psutil   
#from contextlib import contextmanager


# Set up environment before any other imports
if len(sys.argv) > 2:
    os.environ['EDGAR_ROOT_DIR'] = sys.argv[2]  # Set environment variable for edgar root dir


if __name__ == "__main__":
    pid = os.getpid()
    filing_url = sys.argv[1]
    res_url = re.search(r"Archives/edgar/data/(\d+)/(\d+(?:-\d*)*)\D", filing_url)
    if res_url:
        fcik = res_url.group(1) 
        tfnm = res_url.group(2)
        pid = f"{fcik}_{tfnm}"
    logger = setup_logger("main", level=logging.INFO, log_dir="/tmp/log/", pid=pid)
else:
    logger = logging.getLogger("main.openesf.edgar.xbrl_worker")


#@timeout(480.0)
def main():
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
            get_dfs_int = int(sys.argv[5])
        else:
            get_dfs_int = 7
        
        # Check initial memory state
        #check_memory_usage(threshold_gb=memory_threshold_gb)
        
        # Use the existing get_fact_df function
        logger.debug(f"Starting processing with parameters - filing_url: {filing_url}, edgar_local_path: {edgar_local_path}, force_reload: {force_reload}, memory_threshold_gb: {memory_threshold_gb}, get_dfs_int: {get_dfs_int}")
        
        # First try loading the filing to verify it works
            
        # Now try getting the DataFrames
        with memory_check(memory_threshold_gb):
            result = get_xbrl_df(
                filing_url=filing_url,
                edgar_local_path=edgar_local_path,
                force_reload=force_reload,
                memory_threshold_gb=memory_threshold_gb,
                get_dfs_int=int(get_dfs_int)
            )
            
        
        logger.debug(f"get_xbrl_df returned result with keys: {result.keys() if result else 'None'}")
        if result:
            for df_name, df in result.items():
                if df is not None:
                    logger.debug(f"{df_name} shape: {df.shape}")
                else:
                    logger.warning(f"{df_name} is None")
        
        # Check final memory state
        #check_memory_usage(threshold_gb=memory_threshold_gb)
        
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
            logger.debug(f"Checking requested DataFrames: {get_dfs}")
            if get_dfs["fact_df"] and result is not None:
                success = success & bool(type(result["fact_df"]) == pd.DataFrame and len(result["fact_df"]) > 0)
                logger.debug(f"fact_df success: {bool(type(result['fact_df']) == pd.DataFrame and len(result['fact_df']) > 0)}")
            if get_dfs["calc_df"] and result is not None:
                success = success & bool(type(result["calc_df"]) == pd.DataFrame and len(result["calc_df"]) > 0)
                logger.debug(f"calc_df success: {bool(type(result['calc_df']) == pd.DataFrame and len(result['calc_df']) > 0)}")
            if get_dfs["link_df"] and result is not None:
                success = success & bool(type(result["link_df"]) == pd.DataFrame and len(result["link_df"]) > 0)
                logger.debug(f"link_df success: {bool(type(result['link_df']) == pd.DataFrame and len(result['link_df']) > 0)}")
            
        logger.debug(f"Final success status: {success}")
            
        # Success is indicated by process exit code
        if success:
            sys.exit(0)
        else:
            logger.error(f"Worker failed: {result} for {filing_url} " + " ".join(sys.argv))
            sys.exit(1)
        
    except MemoryError as me:
        logger.error(f"Memory error in worker: {me} for {filing_url} and command:" + " ".join(sys.argv))
        sys.exit(2)  # Special exit code for memory errors
    except Exception as e:
        logger.error(f"Worker failed with exception: {str(e)} for {filing_url}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__=="__main__":
    main() 