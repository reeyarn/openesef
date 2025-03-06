"""2025-03-05 12:33:38,561 - main - PID:378766 - ERROR - Error loading filing 
https://www.sec.gov/Archives/edgar/data/715072/0000715072-15-000017.txt: Python int too large to convert to C long
"""

from openesef.edgar.edgar import get_filing_info , EG_LOCAL
from openesef.edgar.loader import get_fact_df #, load_xbrl_filing
from openesef.util.util_mylogger import setup_logger
#from openesef.engines.tax_pres import TaxonomyPresentation, ins_facts

#from openesef.edgar.filing import Filing
from openesef.util.ram_usage import check_memory_usage
import logging
#import os
#import pandas as pd
logger = setup_logger("main", level=logging.INFO, log_dir="/tmp/log/")
from tqdm import tqdm

edgar_local_path='/mnt/text/edgar'
egl = EG_LOCAL(edgar_local_path)

#filings = get_filing_info(forms=['10-K'], year=2016, quarter=0, egl=egl)
#filings = get_filing_info(forms=['10-K'], year=2017, quarter=0, egl=egl)
#filings = get_filing_info(forms=['10-K'], year=2018, quarter=0, egl=egl)
#filings = get_filing_info(forms=['10-K'], year=2019, quarter=0, egl=egl)
#filings = get_filing_info(forms=['10-K'], year=2020, quarter=0, egl=egl)

#filings = get_filing_info(forms=['10-K'], year=2021, quarter=0, egl=egl)
filings = get_filing_info(forms=['10-K'], year=2022, quarter=0, egl=egl) #resubmitted after adding gc.collect()
#filings = get_filing_info(forms=['10-K'], year=2023, quarter=0, egl=egl) #terminated mem leak
#filings = get_filing_info(forms=['10-K'], year=2024, quarter=0, egl=egl)
#filings = get_filing_info(forms=['10-K'], year=2015, quarter=0, egl=egl) #terminated mem leak
for filing in tqdm(filings):
    #filing = filings[0]
    #filing = Filing(url="https://www.sec.gov/Archives/edgar/data/715072/0000715072-15-000017.txt", egl=egl)
    print(filing.url)
    fact_df = get_fact_df(filing.url, edgar_local_path=edgar_local_path, force_reload=True)
    check_memory_usage(threshold_gb=64)
    del fact_df
    # fcik = filing.cik
    # tfnm = filing.url.split("/")[-1]
    # tfnm = tfnm.split(".")[0]
    # file_name = f"{edgar_local_path}/10k-bycik/{fcik}/{tfnm}/fact_df.parquet"
    # if not os.path.exists(file_name):
    #     xid = None; tax = None; fact_df = None
    #     try:
    #         xid, tax = load_xbrl_filing(filing_url=filing.url)
    #         if xid is not None and tax is not None:
    #             fact_df = ins_facts(xid, tax)
    #             fact_df.to_parquet(file_name)
    #     except Exception as e:
    #         logger.error(f"Error loading filing {filing.url}: {e}")
    #     finally:
    #         del xid, tax, fact_df
    #else:
        #fact_df = pd.read_parquet(file_name)
    #print(fact_df)










