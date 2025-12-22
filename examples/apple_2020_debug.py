# %% [markdown]
# # Example: Apple 2020

# %% [markdown]
# <h1 align="center" style="margin-bottom: 0;">
#     <a href="https://github.com/reeyarn/openesef">
#         <img src="https://raw.githubusercontent.com/reeyarn/openesef/refs/heads/master/markdown/esefdata.svg" alt="Open ESEF" style="max-width: 100%; height: auto;"/>
#     </a>
# </h1>
# <h1 align="center" style="margin-top: 0;margin-bottom: 0;">
#     A Python Library for ESEF and XBRL Filings
#     <br>
#         <img src="https://img.shields.io/badge/Project%20Status-Under%20Development-yellow" alt="Project Status: Under Development - 66% Complete" />
#         <img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License: GPL v3.0" />
# </h1>
# <h1 align="center" style="margin-top: 0;margin-bottom: 0;">
# <div align="center" style="font-size: 14px; margin-top: 0; margin-bottom: 0;">
# <a href="https://github.com/reeyarn/openesef">github.com/reeyarn/openesef</a>
# </div>
# </h1>

# %% [markdown]
# 

# %% [markdown]
# First, lets load the logger:

# %%
import logging
from openesef.util.util_mylogger import setup_logger 
logger = setup_logger("main", logging.CRITICAL, log_dir="/tmp/log/")

# %% [markdown]
# Now, lets load the xbrl filing, using Apple 2020 as an example:

# %%
from openesef.edgar.loader import load_xbrl_filing
xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)
#xid, tax = load_xbrl_filing(filing_url="/Archives/edgar/data/320193/0000320193-20-000096.txt")

# %% [markdown]
# The xbrl filing is loaded and the taxonomy is created.
# 
# Now, lets print the XBRL instance (xid):

# %%
print(xid)


# %% [markdown]
# And the taxonomy (tax):

# %%
print(tax)

# %% [markdown]
# DEI stands for Document and Entity Information. For each XBRL report, there will be a section for DEI,
# and this class is to provide easy access to those commonly-defined DEI attributes.
# 
# Lets print the DEI:

# %%
for i, (key, value) in enumerate(xid.dei.items()):
    print(f"{i}: {key}: {value}")
    if i>7:
        break


# %%
from openesef.engines.tax_pres import TaxonomyPresentation
t_pres = TaxonomyPresentation(tax)


# %%
print("\nConcept Labels in Statement of Operations:")
concepts_statement_of_operations = []

iprint=0
for concept in t_pres.statement_concepts.values():
    if concept['statement_name'] == 'CONSOLIDATEDSTATEMENTSOFOPERATIONS':
        concepts_statement_of_operations.append(concept['concept_qname'])
        print("-"*30)
        print(f"Statement: {concept['statement_name']}")
        print(f"Concept: {concept['concept_qname']}")
        print(f"Label: {concept['label']}")        
        iprint+=1
        if iprint>3:
            break
    


# %%
# Get the current year's main instance context
periods_dict = xid.identify_reporting_contexts()
#import pandas as pd
#print(pd.DataFrame.from_dict(periods_dict, orient='index'))


# %%
current_contexts = [ctx_id for ctx_id, ctx_info in periods_dict.items() 
                    if ctx_info['relative_year'] == 0 and  ctx_info.get('main_context')]

print(current_contexts)

# %%
print("\nFact Values:")
iprint=0
for key, fact in xid.xbrl.facts.items():
    concept_qname = fact.qname if hasattr(fact, 'qname') else 'N/A'  # Get the concept's QName
    context = xid.xbrl.contexts[fact.context_ref]
    period_info = periods_dict.get(fact.context_ref, {})
    period_string = period_info.get('period_string', 'N/A')
    if concept_qname in concepts_statement_of_operations and fact.context_ref in current_contexts:
        print(f"{concept_qname:<90} Value: {fact.value:<15} Context: {period_string}")    
        iprint+=1
        if iprint>7:
            break

# %%
def is_numeric(x):
    try:
        float(x)
        return True
    except (ValueError, TypeError):
        return False


# %%
from openesef.engines.tax_pres import ins_facts

fact_df = ins_facts(xid, tax)
fact_df["val_mln"] = fact_df["value"].apply(lambda x: float(x)/1000000 if is_numeric(x) and float(x) > 1000000 else x)
fact_df.sort_values(by='fact_index', inplace=True)
fact_df = fact_df.loc[fact_df.fact_included ]
current_period_string = fact_df.period_string.value_counts().index[0]
current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)

current_facts.loc[(current_facts['statement_name'] == 'CONSOLIDATEDSTATEMENTSOFOPERATIONS')  , ['fact_index', 'concept_name', 'label', "segment_axis", 'val_mln', 'period_end']].head(30)

current_facts.loc[(current_facts['statement_name'] == 'CONSOLIDATEDSTATEMENTSOFOPERATIONS')  , ["fact_id", 'label', "segment_axis", 'val_mln']].head(30)
