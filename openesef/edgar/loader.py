# openesef/edgar/loader.py
from openesef.base.pool import Pool
from openesef.taxonomy.taxonomy import Taxonomy
from openesef.edgar.edgar import EG_LOCAL
from openesef.edgar.stock import Stock
from openesef.edgar.filing import Filing
from openesef.instance.instance import Instance
from openesef.engines.tax_pres import ins_facts
from openesef.util.ram_usage import check_memory_usage, get_process_memory, mem_tops
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
import json
import tracemalloc

if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.edgar.loader") 


def load_xbrl_filing(ticker=None, year=None, filing_url=None, edgar_local_path='/text/edgar', memory_threshold_gb=16):
    """
    Loads an XBRL filing either by ticker and year or by URL.

    Args:
        ticker (str, optional): Stock ticker symbol. Defaults to None.
        year (int, optional): Filing year. Defaults to None.
        filing_url (str, optional): URL of the filing. Defaults to None.
        edgar_local_path (str, optional): Path to local Edgar repository. Defaults to '/text/edgar'.

    Returns:
        tuple: A tuple containing the Instance object (xid) and the Taxonomy object (this_tax), or (None, None) on failure.
    """
    tracemalloc.start()
    memfs = fs.open_fs('mem://') # Create in-memory filesystem
    egl = EG_LOCAL(edgar_local_path)
    xid = None; this_tax = None
    if ticker and year:
        stock = Stock(ticker, egl=egl)
        filing = stock.get_filing(period='annual', year=year)
    elif filing_url:
        filing = Filing(url=filing_url, egl=egl)
    else:
        logger.error("Either ticker and year or filing_url must be provided.")
        return None, None

    if not filing:
        logger.error("Filing not found.")
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
    mem_tops(top_n=10)
    check_memory_usage(threshold_gb=memory_threshold_gb)
    
    xid = None
    if filing.xbrl_files.get("xml"):
        xml_filename = filing.xbrl_files.get("xml")
        instance_str = filing.documents[xml_filename].doc_text.data
        instance_str = list(instance_str.values())[0] if isinstance(instance_str, dict) else instance_str
        instance_byte = instance_str.encode('utf-8')
        instance_io = BytesIO(instance_byte)
        instance_tree = lxml_etree.parse(instance_io)
        root = instance_tree.getroot()
        data_pool.cache_from_string(location=xml_filename, content=instance_str, memfs=memfs)
        xid = Instance(container_pool=data_pool, root=root, memfs=memfs)
        mem_tops(top_n=10)
        check_memory_usage(threshold_gb=memory_threshold_gb)
        
    else:
        logger.warning("No XML instance document found in filing.")

    return xid, tax

def get_fact_df(filing_url, edgar_local_path='/text/edgar', force_reload=False, memory_threshold_gb=16):
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
        
        if os.path.exists(file_name) and not force_reload:
            fact_df = pd.read_parquet(file_name)
            return fact_df
        else:
            try:
                # Monitor memory before loading
                initial_memory = get_process_memory()
                logger.debug(f"Initial memory usage: {initial_memory:.1f}GB")
                
                # Load filing with memory checks
                xid, tax = load_xbrl_filing(filing_url=filing_url)
                check_memory_usage(threshold_gb=memory_threshold_gb)
                
                # Generate facts with memory checks
                fact_df = ins_facts(xid, tax)
                if fact_df is None:
                    logger.warning(f"Error generating fact_df (is None) for {filing_url}")
                    return None
                check_memory_usage(threshold_gb=memory_threshold_gb)
                
                # Save to parquet with memory checks
                fact_df.to_pickle(file_name, compression="gzip")
                try:
                    fact_df.to_parquet(file_name.replace(".p.gz",".parquet"))   
                except Exception as e:
                    try:
                        # Convert all columns to string type before saving to parquet
                        fact_df_str = fact_df.astype(str)
                        fact_df_str.to_parquet(file_name.replace(".p.gz",".parquet"))   
                    except Exception as e:
                        logger.error(f"Error saving fact_df to {file_name}: {e}")                    
                    
                logger.critical(f"\n\n---\n\nSUCCESS: Saved fact_df to {file_name}\n===\n")
                final_memory = get_process_memory()
                logger.debug(f"Final memory usage: {final_memory:.1f}GB")
                
                return fact_df
                
            except MemoryError as me:
                logger.error(f"Memory error processing {filing_url}: {me}")
                return None
            except Exception as e:
                logger.error(f"Error loading filing {filing_url}: {e}")
                return None
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
                cleanup_memory = get_process_memory()
                #logger.info(f"Memory after cleanup: {cleanup_memory:.1f}GB")
    
    return None

def run_xbrl_worker(filing_url, edgar_local_path='/text/edgar', force_reload=False, memory_threshold_gb=8):
    """Run XBRL worker in a separate process."""
    try:
        worker_path = os.path.join(os.path.dirname(__file__), "xbrl_worker.py")
        process = subprocess.Popen(
            [
                sys.executable,
                worker_path,
                filing_url,
                edgar_local_path,
                str(force_reload),
                str(memory_threshold_gb)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        try:
            stdout, stderr = process.communicate(timeout=3600)  # 1 hour timeout
            
            if stderr:
                logger.error(f"Worker stderr for {filing_url}: {stderr}")
            
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

def get_fact_df_wrapper(filing_url, edgar_local_path='/text/edgar', force_reload=False, memory_threshold_gb=16):
    """
    Wrapper that runs fact extraction in a separate process for memory safety.
    
    Args:
        filing_url (str): The URL of the filing
        edgar_local_path (str): Path to local Edgar repository
        force_reload (bool): Whether to force reload
        memory_threshold_gb (int): Memory threshold in GB
        
    Returns:
        bool: True if processing was successful, False otherwise
    """
    try:
        success = run_xbrl_worker(
            filing_url=filing_url,
            edgar_local_path=edgar_local_path,
            force_reload=force_reload,
            memory_threshold_gb=memory_threshold_gb
        )
        return success
    except Exception as e:
        logger.error(traceback.format_exc(limit=10))
        logger.error(f"Error in wrapper: {e}")
        return False

if __name__ == "__main__":
    filing_url = "https://www.sec.gov/Archives/edgar/data/1000298/0001558370-22-003437.txt"
    get_fact_df(filing_url)
    run_xbrl_worker(
            filing_url, 
            edgar_local_path='/text/edgar', 
            force_reload=False,
            memory_threshold_gb=4
    )