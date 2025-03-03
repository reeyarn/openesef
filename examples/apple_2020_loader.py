from openesef.util.util_mylogger import setup_logger 
from openesef.engines import tlb_reporter
from openesef.engines import tax_reporter
from openesef.base import const, util
import logging 
from itertools import chain
from openesef.util.parse_concepts import ins_facts, tax_pre
import pandas as pd
if __name__=="__main__":
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.edgar") 

from openesef.edgar.loader import load_xbrl_filing




if __name__ == "__main__":
    xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)
    reporter = tax_reporter.TaxonomyReporter(tax)
    periods_dict = xid.identify_reporting_contexts()
    concept_df = tax_pre(tax, reporter)
    fact_df = ins_facts(xid, tax, concept_df, periods_dict)
    df1 = pd.merge(fact_df, concept_df, left_on="concept_qname", right_on="concept_qname")            
    df1.loc[df1.statement_name == "us-gaap:IncomeStatementAbstract"].reset_index(drop=True).to_excel("/tmp/apple_2020_income_statement.xlsx")