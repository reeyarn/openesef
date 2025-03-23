"""




2025-03-06 15:43:37,418 - main.openesf.edgar.loader - PID:697134 - ERROR - Error loading filing https://www.sec.gov/Archives/edgar/data/1025378/0001025378-22-000041.txt: ("Could not convert 'false' with type str: tried to convert to double", 'Conversion failed for column value with type object')
88546 - ERROR - Worker stderr for https://www.sec.gov/Archives/edgar/data/1032033/0001628280-17-001725.txt: Error processing label link: can only concatenate str (not "NoneType") to str
 Worker stderr for https://www.sec.gov/Archives/edgar/data/1036030/0001174947-17-000416.txt: Error loading filing https://www.sec.gov/Archives/edgar/data/1036030/0001174947-17-000416.txt: 'statement_name'
.edgar.loader - PID:27494 - ERROR - Worker stderr for https://www.sec.gov/Archives/edgar/data/1039466/0001185185-15-000046.txt: Error processing calculation linkbase mem://xsnx-20140930_cal.xml: '_cython_3_0_11.cython_function_or_method' object has no attribute 'lower'
Error processing label link: '_cython_3_0_11.cython_function_or_method' object has no attribute 'endswith'

"""

# openesef/edgar/loader.py
from openesef.base.pool import Pool
from openesef.taxonomy.taxonomy import Taxonomy
from openesef.edgar.edgar import EG_LOCAL
from openesef.edgar.stock import Stock
from openesef.edgar.filing import Filing
from openesef.instance.instance import Instance
from typing import Union, Tuple
from openesef.engines.tax_pres import tax_calc_df, TaxonomyPresentation
from openesef.engines.ins_facts import ins_facts
#from openesef.util.ram_usage import check_memory_usage, get_process_memory, mem_tops
#from openesef.util.ram_usage import timeout
#import tracemalloc
import fs
from lxml import etree as lxml_etree
from io import BytesIO
import logging
import re
import os
import pandas as pd
import warnings

# Specifically ignore only SettingWithCopyWarning
#warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)

import gc
#import psutil
#import time
#logger = logging.getLogger(__name__) # Get logger for this module
import traceback
from openesef.util.util_mylogger import setup_logger 
import subprocess
import sys
#import json

#import gzip
#import pickle
from datetime import datetime
#from openesef.version import PICKLE_VERSION
from openesef.edgar.verpkl import VersionedPickle
import psutil
import time

if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/", full_format=False)
else:
    logger = logging.getLogger("main.openesf.edgar.loader") 



# import psutil   
# from contextlib import contextmanager
# @contextmanager
# def memory_check(threshold_gb: int):
#     try:
#         yield
#     finally:
#         if psutil.Process(os.getpid()) > threshold_gb:
#             raise MemoryError(f"Memory usage exceeded {threshold_gb}GB threshold")

def get_edgar_local_path():
    edgar_local_path = None
    if os.path.isdir("/mnt/text/edgar/"):
        edgar_local_path =  "/mnt/text/edgar/"
    elif os.path.isdir("/text/edgar/"):
        edgar_local_path = "/text/edgar/"
    else:
        logger.warning("No edgar local path found")
        edgar_local_path = "edgar"
    logger.info(f"Using edgar_local_path: {edgar_local_path}")
    return edgar_local_path

def get_xbrl_df_by_ticker_year(ticker, year, force_reload=False, memory_threshold_gb=16, 
                               edgar_local_path = get_edgar_local_path()):
    egl = EG_LOCAL(edgar_local_path)
    stock = Stock(ticker, egl=egl)
    filing = stock.get_filing(period='annual', year=year)
    
    return get_xbrl_df(filing.url, force_reload=force_reload, edgar_local_path=edgar_local_path)


def load_xbrl_filing(ticker=None, year=None, filing_url=None, edgar_local_path=get_edgar_local_path(), memory_threshold_gb=16, return_data_pool=False):
    """
    Loads an XBRL filing either by ticker and year or by URL.

    Args:
        ticker (str, optional): Stock ticker symbol. Defaults to None.
        year (int, optional): Filing year. Defaults to None.
        filing_url (str, optional): URL of the filing. Defaults to None.
        edgar_local_path (str, optional): Path to local Edgar repository. Defaults to '/mnt/text/edgar'.

    Returns:
        tuple: A tuple containing the Instance object (xid) and the Taxonomy object (tax), or (None, None) on failure.
    """
    #tracemalloc.start()
    memfs = fs.open_fs('mem://') # Create in-memory filesystem
    #edgar_local_path='/mnt/text/edgar'
    egl = EG_LOCAL(edgar_local_path)
    xid = None; tax = None; 
    #cik = None; tfnm = None; cache_dir = None; xid_cache = None; tax_cache = None; dpl_cache = None
    #ticker="AAPL"; year=2010
    if ticker and year:
        stock = Stock(ticker, egl=egl)
        filing = stock.get_filing(period='annual', year=year)
        #cik = stock.cik; tfnm = filing.tfnm
    elif filing_url:
        filing = Filing(url=filing_url, egl=egl)
        #cik = filing.cik; tfnm = filing.tfnm
    else:
        logger.error("Either ticker and year or filing_url must be provided.")
        if return_data_pool:
            return None, None, None
        else:
            return None, None

    if not filing:
        logger.error("Filing not found.")
        if return_data_pool:
            return None, None, None
        else:
            return None, None

    if not filing.xbrl_files:
        logger.warning(f"No XBRL files found in filing {filing_url}")
        if return_data_pool:
            return None, None, None
        else:
            return None, None

    entry_points = []
    for key, filename in filing.xbrl_files.items():
        logger.debug(f"Caching XBRL file: {key}, {filename}")
        content = filing.documents[filename].doc_text.data
        content = list(content.values())[0] if isinstance(content, dict) else content
        with memfs.open(filename, 'w') as f:
            f.write(content)
        logger.debug(f"Cached {filename} to memory, length={len(content)}")
        if "xml" in filename:
            entry_points.append(f"mem://{filename}")

    data_pool = Pool(max_error=32, esef_filing_root="mem://", memfs=memfs)
    tax = Taxonomy(
        entry_points=entry_points,
        container_pool=data_pool,
        esef_filing_root="mem://",
        memfs=memfs
    )
    data_pool.current_taxonomy = tax
    # mem_tops(top_n=10)
    # check_memory_usage(threshold_gb=memory_threshold_gb)
    
    xid = None
    if filing.xbrl_files.get("xml"):
        xml_filename = filing.xbrl_files.get("xml")
        instance_str = filing.documents[xml_filename].doc_text.data
        instance_str = list(instance_str.values())[0] if isinstance(instance_str, dict) else instance_str
        instance_byte = instance_str.encode('utf-8')
        instance_io = BytesIO(instance_byte)
        instance_tree = lxml_etree.parse(instance_io)
        root = instance_tree.getroot()
        #data_pool.cache_from_string(location=xml_filename, content=instance_str, memfs=memfs)
        xid = Instance(container_pool=data_pool, root=root, memfs=memfs)
        
        data_pool.add_taxonomy(entry_points, esef_filing_root="mem://", memfs=memfs)
        data_pool.add_instance(xid, key=f"mem://{xml_filename}", attach_taxonomy=False)
        #xid.pool.instances
        # mem_tops(top_n=10)
        # check_memory_usage(threshold_gb=memory_threshold_gb)
        
    else:
        logger.warning("No XML instance document found in filing.")
        if return_data_pool:    
            return None, None, None
        else:
            return None, None


    
    if return_data_pool:
        return xid, tax, data_pool
    else:
        return xid, tax

def get_fact_df(
    filing_url: str, 
    edgar_local_path: str = '/mnt/text/edgar', 
    force_reload: bool = False, 
    memory_threshold_gb: int = 16, 
    return_calc_df: bool = False
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Get a fact DataFrame from an Instance and Taxonomy object.

    Args:
        filing_url (str): The URL of the filing.
        edgar_local_path (str, optional): The path to the local Edgar repository. Defaults to '/mnt/text/edgar'.
        force_reload (bool, optional): Whether to force a reload of the fact DataFrame. Defaults to False.
        memory_threshold_gb (float, optional): Maximum allowed memory usage in GB. Defaults to 60.

    Returns:
        pd.DataFrame: A DataFrame containing the facts.
        
    Raises:
        MemoryError: If memory usage exceeds the threshold
    """
    res_url = re.search(r"Archives/edgar/data/(\d+)/(\d+(?:-\d*)*)\D", filing_url)
    fact_df = None
    xid = None
    tax = None
    
    if res_url:
        fcik = res_url.group(1) 
        tfnm = res_url.group(2)
        file_name = f"{edgar_local_path}/10k-bycik/{fcik}/{tfnm}/fact_df.p.gz"
        calc_df_file_name = f"{edgar_local_path}/10k-bycik/{fcik}/{tfnm}/calc_df.p.gz"  
        
        if os.path.exists(file_name) and not force_reload:
            try:
                fact_df = pd.read_pickle(file_name, compression="gzip")
            except Exception as e:
                logger.warning(f"Cannot load fact_df from {file_name}: {e} due to numpy version conflict between pickled and loading. Lets recreate.")
                fact_df = None
            if fact_df is None:
                if return_calc_df and fact_df is not None:
                    if os.path.exists(calc_df_file_name):
                        calc_df = pd.read_pickle(calc_df_file_name, compression="gzip")    
                        logger.info(f"\n\n---\n\nSUCCESS: Loaded fact_df from {file_name} and calc_df from {calc_df_file_name}\n===\n")
                        return fact_df, calc_df
                    else:
                        xid, tax = load_xbrl_filing(filing_url=filing_url)
                        if xid is None or tax is None:
                            logger.warning(f"Error loading xid or tax for {filing_url}")
                            return None, None if return_calc_df else None
                        calc_df = tax_calc_df(tax)
                        calc_df.to_pickle(calc_df_file_name, compression="gzip")
                        logger.info(f"\n\n---\n\nSUCCESS: Loaded fact_df from {file_name} and built calc_df from {calc_df_file_name}\n===\n")
                        return fact_df, calc_df
                else:
                    logger.info(f"\n\n---\n\nSUCCESS: Loaded fact_df from {file_name} and did not build calc_df\n===\n")
                    return fact_df
        try:
            xid, tax = load_xbrl_filing(filing_url=filing_url)
            if xid is None or tax is None:
                logger.warning(f"Error loading xid or tax for {filing_url}")
                return None, None if return_calc_df else None
            # Generate facts with memory checks
            fact_df = ins_facts(xid, tax)
            if fact_df is None:
                logger.warning(f"Error generating fact_df (is None) for {filing_url}")
                return None, None if return_calc_df else None
            fact_df.to_pickle(file_name, compression="gzip")

            calc_df = tax_calc_df(tax)
            calc_df.to_pickle(calc_df_file_name, compression="gzip")

            try:
                fact_df.to_parquet(file_name.replace(".p.gz",".parquet"))   
                calc_df.to_parquet(calc_df_file_name.replace(".p.gz",".parquet"))
            except Exception as e:
                try:
                    # Convert all columns to string type before saving to parquet
                    fact_df_str = fact_df.astype(str)
                    fact_df_str.to_parquet(file_name.replace(".p.gz",".parquet"))   
                except Exception as e:
                    logger.error(f"Error saving fact_df to {file_name}: {e}")                    
                
            logger.info(f"\n\n---\n\nSUCCESS: Saved fact_df to {file_name}\n===\n")
            # final_memory = get_process_memory()
            # logger.debug(f"Final memory usage: {final_memory:.1f}GB")
            if return_calc_df:
                return fact_df, calc_df
            else:
                return fact_df
            
        except MemoryError as me:
            logger.error(f"Memory error processing {filing_url}: {me}")
            return None, None if return_calc_df else None
        except Exception as e:
            logger.error(f"Error loading filing {filing_url}: {e}")
            return None, None if return_calc_df else None
        finally:
            # Explicit cleanup
            if 'xid' in locals():
                del xid
            if 'tax' in locals():
                del tax
            if 'fact_df' in locals():
                del fact_df
            gc.collect()
            
            # Log memory after cleanup
            #cleanup_memory = get_process_memory()
            #logger.info(f"Memory after cleanup: {cleanup_memory:.1f}GB")
    
    return None, None if return_calc_df else None


def get_xbrl_df(filing_url, edgar_local_path='/mnt/text/edgar', force_reload=False, memory_threshold_gb=16, get_dfs_int = None):
    """
    Get a fact DataFrame from an Instance and Taxonomy object.

    Args:
        filing_url (str): The URL of the filing.
        edgar_local_path (str, optional): The path to the local Edgar repository. Defaults to '/mnt/text/edgar'.
        force_reload (bool, optional): Whether to force a reload of the fact DataFrame. Defaults to False.
        memory_threshold_gb (float, optional): Maximum allowed memory usage in GB. Defaults to 60.

    Returns:
        pd.DataFrame: A DataFrame containing the facts.
        
    Raises:
        MemoryError: If memory usage exceeds the threshold
    """
    success = True
    result_dfs = {"fact_df": None, "calc_df": None, "link_df": None}
    
    fact_df = None
    xid = None
    tax = None

    # Initialize default get_dfs dictionary
    get_dfs = {"fact_df": False, "calc_df": False, "link_df": False}

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
        logger.debug(f"get_dfs: {get_dfs}")
    else:
        get_dfs = {"fact_df": True, "calc_df": True, "link_df": True}
    logger.info(f"get_dfs: {get_dfs}")    
    res_url = re.search(r"Archives/edgar/data/(\d+)/(\d+(?:-\d*)*)\D", filing_url)
    if res_url:
        fcik = res_url.group(1) 
        tfnm = res_url.group(2)
        fact_df_file_name = f"{edgar_local_path}/10k-bycik/{fcik}/{tfnm}/fact_df.p.gz"
        calc_df_file_name = f"{edgar_local_path}/10k-bycik/{fcik}/{tfnm}/calc_df.p.gz"  
        link_df_file_name = f"{edgar_local_path}/10k-bycik/{fcik}/{tfnm}/link_df.p.gz"
        
        logger.debug(f"Processing files - fact_df: {fact_df_file_name}, calc_df: {calc_df_file_name}, link_df: {link_df_file_name}")
        logger.debug(f"File existence - fact_df: {os.path.exists(fact_df_file_name)}, calc_df: {os.path.exists(calc_df_file_name)}, link_df: {os.path.exists(link_df_file_name)}")
        logger.debug(f"Force reload: {force_reload}")
        if force_reload:
            success = False
        if get_dfs["fact_df"] and not force_reload:
            if os.path.exists(fact_df_file_name):    
                try:
                    fact_df = pd.read_pickle(fact_df_file_name, compression="gzip")
                    result_dfs["fact_df"] = fact_df
                    success = True & success
                    logger.debug(f"Successfully loaded fact_df from {fact_df_file_name}")
                except Exception as e:
                    logger.warning(f"Cannot load fact_df from {fact_df_file_name}: {e} due to numpy version conflict between pickled and loading. Lets recreate.")
                    fact_df = None
                    success = False
            else:
                logger.info(f"Fact_df file {fact_df_file_name} does not exist. Lets recreate.")
                success = False
            
        if get_dfs["calc_df"]  and not force_reload:
            if os.path.exists(calc_df_file_name):    
                try: 
                    calc_df = pd.read_pickle(calc_df_file_name, compression="gzip")    
                    result_dfs["calc_df"] = calc_df
                    success = True & success
                    logger.debug(f"Successfully loaded calc_df from {calc_df_file_name}")
                except Exception as e:
                    logger.warning(f"Cannot load calc_df from {calc_df_file_name}: {e} due to numpy version conflict between pickled and loading. Lets recreate.")
                    calc_df = None
                    success = False
            else:
                logger.info(f"Calc_df file {calc_df_file_name} does not exist. Lets recreate.")
                success = False
            
        if get_dfs["link_df"]  and not force_reload:
            if os.path.exists(link_df_file_name):    
                try:
                    link_df = pd.read_pickle(link_df_file_name, compression="gzip")
                    result_dfs["link_df"] = link_df
                    success = True & success
                    logger.debug(f"Successfully loaded link_df from {link_df_file_name}")
                except Exception as e:
                    logger.warning(f"Cannot load link_df from {link_df_file_name}: {e} due to numpy version conflict between pickled and loading. Lets recreate.")
                    link_df = None
                    success = False
            else:
                logger.info(f"Link_df file {link_df_file_name} does not exist. Lets recreate.")
                success = False 
        if success:
            logger.debug("Successfully loaded all requested DataFrames from cache")
            return result_dfs
        
        try:
            logger.debug("Loading filing for DataFrame generation...")
            xid, tax = load_xbrl_filing(filing_url=filing_url)
            if xid is None or tax is None:
                logger.warning(f"Error loading xid or tax for {filing_url}")
                return result_dfs
            logger.debug(f"Successfully loaded filing - xid: {xid}, tax: {tax}")
            
            # Generate facts with memory checks
            if get_dfs["fact_df"]:
                logger.debug("Generating fact_df...")
                fact_df = ins_facts(xid, tax)
                if fact_df is None:
                    logger.warning(f"Error generating fact_df (is None) for {filing_url}")
                else:
                    fact_df.to_pickle(fact_df_file_name, compression="gzip")
                    fact_df.to_csv(fact_df_file_name.replace(".p.gz",".csv.gz"), index=False, compression="gzip", sep="|")
                    result_dfs["fact_df"] = fact_df
                    logger.debug(f"Successfully generated and saved fact_df with shape {fact_df.shape}")

            if get_dfs["calc_df"]:
                logger.debug("Generating calc_df...")
                calc_df = tax_calc_df(tax)
                if calc_df is None:
                    logger.warning(f"Error generating calc_df (is None) for {filing_url}")
                else:   
                    calc_df.to_pickle(calc_df_file_name, compression="gzip")
                    calc_df.to_csv(calc_df_file_name.replace(".p.gz",".csv.gz"), index=False, compression="gzip", sep="|")
                    result_dfs["calc_df"] = calc_df
                    logger.debug(f"Successfully generated and saved calc_df with shape {calc_df.shape}")

            if get_dfs["link_df"]:
                logger.debug("Generating link_df...")
                t_pres = TaxonomyPresentation(tax)
                link_df = t_pres.link_df
                if link_df is None:
                    logger.warning(f"Error generating link_df (is None) for {filing_url}")
                else:
                    link_df.to_pickle(link_df_file_name, compression="gzip")
                    link_df.to_csv(link_df_file_name.replace(".p.gz",".csv.gz"), index=False, compression="gzip", sep="|")
                    result_dfs["link_df"] = link_df
                    logger.debug(f"Successfully generated and saved link_df with shape {link_df.shape}")

            logger.debug(f"Final result_dfs keys: {result_dfs.keys()}")
            for df_name, df in result_dfs.items():
                logger.debug(f"{df_name} is {'not None' if df is not None else 'None'}")
                if df is not None:
                    logger.debug(f"{df_name} shape: {df.shape}")
                
            return result_dfs
            
        except MemoryError as me:
            logger.error(f"Memory error processing {filing_url}: {me}")
            return None
        except Exception as e:
            logger.error(f"Error loading filing {filing_url}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None



def run_xbrl_worker(filing_url, edgar_local_path='/mnt/text/edgar', force_reload=False, memory_threshold_gb=16, get_dfs_int=7):
    """Run XBRL worker in a separate process and monitor its memory usage."""
    try:
        worker_path = os.path.join(os.path.dirname(__file__), "xbrl_worker.py")
        process = subprocess.Popen(
            [
                sys.executable,
                worker_path,
                str(filing_url),
                str(edgar_local_path),
                str(force_reload),  # Convert boolean to string
                str(memory_threshold_gb),
                str(get_dfs_int)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Monitor memory usage while process is running
        waiting_time = 0
        while process.poll() is None and waiting_time < 240:  # While process is still running
            try:
                # Get process memory info using psutil
                proc = psutil.Process(process.pid)
                memory_gb = proc.memory_info().rss / 1024 / 1024 / 1024  # Convert bytes to GB
                
                if memory_gb > memory_threshold_gb:
                    logger.warning(f"Worker memory usage ({memory_gb:.1f}GB) exceeded threshold ({memory_threshold_gb}GB)")
                    process.kill()
                    return False
                
                # Log memory usage every 30 seconds
                if hasattr(run_xbrl_worker, '_last_log_time'):
                    if time.time() - run_xbrl_worker._last_log_time > 30:
                        logger.debug(f"Worker memory usage: {memory_gb:.1f}GB")
                        run_xbrl_worker._last_log_time = time.time()
                else:
                    run_xbrl_worker._last_log_time = time.time()
                
                # Sleep to avoid excessive CPU usage
                time.sleep(3)
                waiting_time += 3
            except psutil.NoSuchProcess:
                # Process already terminated
                break
            except Exception as e:
                logger.error(f"Error monitoring worker memory: {e}")
                break
        
        try:
            stdout, stderr = process.communicate(timeout=240)  # 4 min timeout
            
            if stderr:
                logger.error(f"Worker stderr for {filing_url}: {stderr}." + " ".join([
                    sys.executable,
                    worker_path,
                    filing_url,
                    edgar_local_path,
                    str(force_reload).lower(),
                    str(memory_threshold_gb),
                    str(get_dfs_int)
                ]) )
            
            # Check exit code
            if process.returncode == 2:  # Memory error
                logger.error(f"Worker exceeded memory limits for {filing_url}")
                return False
            return process.returncode == 0
            
        except subprocess.TimeoutExpired:
            process.kill()
            logger.error(f"Worker timed out after 4 minutes for {filing_url}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to run worker for {filing_url}: {e}")
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__" and False:
    filing_url = "https://www.sec.gov/Archives/edgar/data/1000298/0001558370-22-003437.txt"
    get_fact_df(filing_url)
    run_xbrl_worker(
            filing_url, 
            edgar_local_path='/mnt/text/edgar', 
            force_reload=False,
            memory_threshold_gb=4
    )



def main():    
    #("Expected bytes, got a 'float' object", 'Conversion failed for column value with type object')
    #filing_url = "https://www.sec.gov/Archives/edgar/data/1039466/0001185185-15-000046.txt"
    #filing_url = "'https://www.sec.gov/Archives/edgar/data/1013871/0001013871-22-000010.txt'"
    filing_url = "https://www.sec.gov/Archives/edgar/data/1013871/0001013871-22-000010.txt"
    try:
        result = run_xbrl_worker(
            filing_url=filing_url,
            edgar_local_path='/mnt/text/edgar',
            force_reload=True,
            memory_threshold_gb=16, 
            get_dfs_int=7
        )
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
    #print(result)
    xid, tax, data_pool = load_xbrl_filing(filing_url=filing_url, return_data_pool=True)
    print(result)
    exit()
    xid, tax, data_pool = load_xbrl_filing(filing_url=filing_url, return_data_pool=True)
    filing = Filing(url=filing_url, egl=EG_LOCAL('/mnt/text/edgar'))
    fact_df = get_fact_df(filing.url)
    calc_df = tax_calc_df(tax)
    #def get_xbrl_df(filing_url, edgar_local_path='/mnt/text/edgar', force_reload=False, memory_threshold_gb=16, get_dfs_int = None):
    xbrl_df_dict = get_xbrl_df(filing.url,edgar_local_path='/mnt/text/edgar', force_reload=False, memory_threshold_gb=16, get_dfs_int=7)

    print(xbrl_df_dict["link_df"])

if __name__ == "__main__":    
    main()    