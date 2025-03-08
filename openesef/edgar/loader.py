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
from openesef.engines.tax_pres import ins_facts, tax_calc_df
#from openesef.util.ram_usage import check_memory_usage, get_process_memory, mem_tops
#import tracemalloc
import fs
from lxml import etree as lxml_etree
from io import BytesIO
import logging
import re
import os
import pandas as pd
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
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/log/", full_format=False)
else:
    logger = logging.getLogger("main.openesf.edgar.loader") 


def load_xbrl_filing(ticker=None, year=None, filing_url=None, edgar_local_path='/text/edgar', memory_threshold_gb=16, return_data_pool=False):
    """
    Loads an XBRL filing either by ticker and year or by URL.

    Args:
        ticker (str, optional): Stock ticker symbol. Defaults to None.
        year (int, optional): Filing year. Defaults to None.
        filing_url (str, optional): URL of the filing. Defaults to None.
        edgar_local_path (str, optional): Path to local Edgar repository. Defaults to '/text/edgar'.

    Returns:
        tuple: A tuple containing the Instance object (xid) and the Taxonomy object (tax), or (None, None) on failure.
    """
    #tracemalloc.start()
    memfs = fs.open_fs('mem://') # Create in-memory filesystem
    #edgar_local_path='/text/edgar'
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

def get_fact_df(filing_url, edgar_local_path='/text/edgar', force_reload=False, memory_threshold_gb=16, return_calc_df=False):
    """
    Get a fact DataFrame from an Instance and Taxonomy object.

    Args:
        filing_url (str): The URL of the filing.
        edgar_local_path (str, optional): The path to the local Edgar repository. Defaults to '/text/edgar'.
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
                        calc_df = tax_calc_df(tax)
                        calc_df.to_pickle(calc_df_file_name, compression="gzip")
                        logger.info(f"\n\n---\n\nSUCCESS: Loaded fact_df from {file_name} and built calc_df from {calc_df_file_name}\n===\n")
                        return fact_df, calc_df
                else:
                    logger.info(f"\n\n---\n\nSUCCESS: Loaded fact_df from {file_name} and did not build calc_df\n===\n")
                    return fact_df
        try:
            xid, tax = load_xbrl_filing(filing_url=filing_url)
            
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

def run_xbrl_worker(filing_url, edgar_local_path='/text/edgar', force_reload=False, memory_threshold_gb=16, return_calc_df=True):
    """Run XBRL worker in a separate process and monitor its memory usage."""
    try:
        worker_path = os.path.join(os.path.dirname(__file__), "xbrl_worker.py")
        process = subprocess.Popen(
            [
                sys.executable,
                worker_path,
                filing_url,
                edgar_local_path,
                str(force_reload),
                str(memory_threshold_gb),
                str(return_calc_df)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Monitor memory usage while process is running
        while process.poll() is None:  # While process is still running
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
                time.sleep(1)
                
            except psutil.NoSuchProcess:
                # Process already terminated
                break
            except Exception as e:
                logger.error(f"Error monitoring worker memory: {e}")
                break
        
        try:
            stdout, stderr = process.communicate(timeout=3600)  # 1 hour timeout
            
            if stderr:
                logger.error(f"Worker stderr for {filing_url}: {stderr}." + " ".join([
                    sys.executable,
                    worker_path,
                    filing_url,
                    edgar_local_path,
                    str(force_reload),
                    str(memory_threshold_gb),
                    str(return_calc_df)
                ]) )
            
            # Check exit code
            if process.returncode == 2:  # Memory error
                logger.error(f"Worker exceeded memory limits for {filing_url}")
                return False
            return process.returncode == 0
            
        except subprocess.TimeoutExpired:
            process.kill()
            logger.error(f"Worker timed out after 1 hour for {filing_url}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to run worker for {filing_url}: {e}")
        return False

# def get_fact_df_wrapper(filing_url, edgar_local_path='/text/edgar', force_reload=False, memory_threshold_gb=16, return_calc_df=True):
#     """
#     Wrapper that runs fact extraction in a separate process for memory safety.
    
#     Args:
#         filing_url (str): The URL of the filing
#         edgar_local_path (str): Path to local Edgar repository
#         force_reload (bool): Whether to force reload
#         memory_threshold_gb (int): Memory threshold in GB
        
#     Returns:
#         bool: True if processing was successful, False otherwise
#     """
#     try:
#         success = run_xbrl_worker(
#             filing_url=filing_url,
#             edgar_local_path=edgar_local_path,
#             force_reload=force_reload,
#             memory_threshold_gb=memory_threshold_gb,
#             return_calc_df=return_calc_df
#         )
#         return success
#     except Exception as e:
#         logger.error(traceback.format_exc(limit=10))
#         logger.error(f"Error in wrapper: {e}")
#         return False

if __name__ == "__main__" and False:
    filing_url = "https://www.sec.gov/Archives/edgar/data/1000298/0001558370-22-003437.txt"
    get_fact_df(filing_url)
    run_xbrl_worker(
            filing_url, 
            edgar_local_path='/text/edgar', 
            force_reload=False,
            memory_threshold_gb=4
    )

if __name__ == "__main__":    
    #("Expected bytes, got a 'float' object", 'Conversion failed for column value with type object')
    filing_url = "https://www.sec.gov/Archives/edgar/data/1039466/0001185185-15-000046.txt"
    result = run_xbrl_worker(
        filing_url=filing_url,
        edgar_local_path='/text/edgar',
        force_reload=False,
        memory_threshold_gb=4, 
        return_calc_df=False
    )
    print(f"Result: {result}")
    
    xid, tax, data_pool = load_xbrl_filing(filing_url=filing_url, return_data_pool=True)
    filing = Filing(url=filing_url, egl=EG_LOCAL('/text/edgar'))
    fact_df = get_fact_df(filing.url)
    calc_df = tax_calc_df(tax)

    calc_arcs = [(k, v) for k, v in tax.base_sets.items() if k[0] == 'calculationArc']
    print(f"Found {len(calc_arcs)} calculation arcs")

    for key in tax.base_sets:
        if key[0] == 'calculationArc':
            print(f"Found calculation arc with role: {key[1]}")

    # Check for calculation arcs in base_sets

    # Print details of each calculation arc
    calc_records = []
    for key, link in calc_arcs:
        rel_count = len(getattr(link, 'relationships', []))
        print(f"\nRole: {key[1]}")
        print(f"Number of relationships: {rel_count}")
        role = key[1]
        # Print first few relationships if any exist
        if hasattr(link, 'relationships'):
            for rel in link.relationships:#[:3]:  # Show first 3 relationships
                #print(f"  {rel['from'].qname} -> {rel['to'].qname} (weight: {rel['weight']})   order {rel['order']}")
                record = {
                    'role': role,
                    'from_qname': str(rel['from'].qname),
                    'to_qname': str(rel['to'].qname),
                    'weight': rel['weight'],
                    'order': rel['order']
                }
                calc_records.append(record)

    calc_df = pd.DataFrame(calc_records)
    print(calc_df)
    #calc_df.to_csv("calc_records.csv", index=False)
    