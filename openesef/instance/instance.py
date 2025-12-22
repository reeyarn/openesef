import os
from openesef.instance import m_xbrl
from openesef.base import fbase, const
from openesef.ixbrl import m_ixbrl
from openesef.instance import dei
from lxml import etree as lxml
import re
from datetime import datetime
from openesef.util.util_mylogger import setup_logger
import logging
if __name__=="__main__":    
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/")
else:
    logger = logging.getLogger("main.openesf.instance.instance")

class Instance(fbase.XmlFileBase):
    def __init__(self, location=None, container_pool=None, root=None, esef_filing_root=None, memfs=None):
        self.pool = container_pool
        self.taxonomy = None
        self.xbrl = None
        self.ixbrl = None
        self.esef_filing_root = esef_filing_root
        parsers = {
            f'{{{const.NS_XHTML}}}html': self.l_ixbrl,
            f'{{{const.NS_XBRLI}}}xbrl': self.l_xbrl
        }
        self.location = location
        
        #20250302 trying to incorporate dei.py into instance.py
        #self.xbrl_document = dei.XBRLDocument(location) # Create an instance of XBRLDocument
        #self.dei = self.xbrl_document.dei # Access DEI information
        
        super().__init__(location, container_pool, parsers, root, esef_filing_root=esef_filing_root, memfs=memfs)
        # DEI information will be available in self.xbrl.dei after parsing
        self.dei = self.xbrl.dei if self.xbrl else {} # Access DEI from XbrlModel

    def __str__(self):
        return self.info()

    def __repr__(self):
        return self.info()

    def info(self):
        return "\n".join([
            f"Namespaces: {len(self.namespaces)}",
            f"Schema references: {len(self.xbrl.schema_refs)}",
            f"Linkbase references: {len(self.xbrl.linkbase_refs)}",
            f"Contexts: {len(self.xbrl.contexts)}",
            f"Units: {len(self.xbrl.units)}",
            f"Facts: {len(self.xbrl.facts)}",
            f"Footnotes: {len(self.xbrl.footnotes)}",
            f"Filing Indicators: {len(self.xbrl.filing_indicators)}"
        ])


    def l_xbrl(self, e):
        self.xbrl = m_xbrl.XbrlModel(e, self) ## XbrlModel will now parse DEI

    def l_ixbrl(self, e):
        self.ixbrl = m_ixbrl.IxbrlModel(e, self)
        # Recursive read all namespaces, because in some cases namespace prefixes
        # are defined deeper in the XML structure.
        self.l_namespaces(e)
        # self.l_namespaces_rec(e, target_tags=[
        #     f'{{{const.NS_IXBRL}}}nonNumeric',
        #     f'{{{const.NS_IXBRL}}}nonFraction'])
        self.ixbrl.strip()
        s = ''.join(self.ixbrl.output)
        parser = lxml.XMLParser(huge_tree=True)
        root = lxml.XML(s, parser)
        self.l_xbrl(root)

    def to_xml(self):
        return self.ixbrl.to_xml() if self.ixbrl else self.xbrl.to_xml() if self.xbrl else None

    def identify_reporting_contexts(self):
        """Identifies key reporting contexts (Current/Prior, Instant/Duration). Added by devv.ai on 20250303"""
        periods_dict = {}
        doc_period_end_date = None
        
        # 1. Get DocumentPeriodEndDate (using DEI - adjust if needed)
        #from openesef.instance import dei
        if self.dei and dei.DEI.DocumentPeriodEndDate in self.dei: # Use DEI if integrated
            doc_period_end_date_str = self.dei[dei.DEI.DocumentPeriodEndDate]
        else: # Fallback: search facts (less robust, but works if DEI not fully ready)
            for key, fact in self.xbrl.facts.items():
                if re.search(r"DocumentPeriodEndDate", str(fact.qname)):
                    doc_period_end_date_str = fact.value
                    break
            else: # No DocumentPeriodEndDate found
                return {} # Or handle error as needed
        
        if doc_period_end_date_str:
            #doc_period_end_date_dt = pd.to_datetime(doc_period_end_date_str)
            #from datetime import datetime
            doc_period_end_date_dt = datetime.strptime(doc_period_end_date_str, '%Y-%m-%d')  # Adjust format as needed
        else:
            return {} # No valid date found
        
        #main_contexts = [context for context in self.xbrl.contexts.values() if not context.descriptors] # Consider main contexts without descriptors
        
        # 1. Current Instance Date Context
        for context in self.xbrl.contexts.values(): # not just in main_contexts
            if context.period_instant is not None:
                context_instant_dt = datetime.strptime(context.period_instant, '%Y-%m-%d')
                if abs((context_instant_dt - doc_period_end_date_dt).days) <= 10:  # Check if within 10 days
                    this_context_dict = {
                        "context_id": context.id,
                        "period_string": context.get_period_string(),
                        "instant": context.period_instant,
                        "main_context": bool(not context.descriptors),
                        "relative_year": 0,
                        "segment": context.segment,
                        "scenario": context.scenario
                    }
                    if context.descriptors:
                        for key, value in context.descriptors.items():
                            this_context_dict[key] = value
                    periods_dict[this_context_dict["context_id"]] = this_context_dict
                    #break # Assuming only one current instance context
        
        # 2. Current Period Context (Annual)
        #periods_dict["CurrentPeriodContext"] = None
        if doc_period_end_date_dt:
            for context_id, context in self.xbrl.contexts.items(): # Iterate ALL contexts for period context
                if context.period_start is not None and context.period_end is not None : # Still using descriptor filter for 'main' period context
                    period_start_dt = datetime.strptime(context.period_start, '%Y-%m-%d')
                    period_end_dt = datetime.strptime(context.period_end, '%Y-%m-%d')
                    if (period_end_dt - period_start_dt).days >= 360 and str(period_end_dt.date()) == str(doc_period_end_date_dt.date()):
                        this_context_dict = {
                            "context_id": context_id,
                            "period_string": context.get_period_string(),
                            "start_date": context.period_start,
                            "end_date": context.period_end,
                            "main_context": bool(not context.descriptors),
                            "relative_year": 0
                        }
                        periods_dict[this_context_dict["context_id"]] = this_context_dict
                        #break # Assuming only one current period context

        # 3. Prior Instance Date Context
        #periods_dict["PriorInstanceDateContext"] = None
        closest_prior_instant = None
        closest_prior_context_id = None
        if doc_period_end_date_dt:
            for context_id, context in self.xbrl.contexts.items(): # Iterate ALL contexts for prior context
                if context.period_instant is not None : # Still using descriptor filter for 'main' prior context
                    try:
                        context_instant_dt = datetime.strptime(context.period_instant, '%Y-%m-%d')
                        if context_instant_dt < doc_period_end_date_dt:
                            if closest_prior_instant is None or (doc_period_end_date_dt - context_instant_dt) < (doc_period_end_date_dt - closest_prior_instant):
                                closest_prior_instant = context_instant_dt
                                closest_prior_context_id = context_id
                                #if closest_prior_context_id:
                                this_context_dict = {
                                    "context_id": closest_prior_context_id,
                                    "period_string": self.xbrl.contexts[closest_prior_context_id].get_period_string(),
                                    "instant": self.xbrl.contexts[closest_prior_context_id].period_instant,
                                    "main_context": bool(not self.xbrl.contexts[closest_prior_context_id].descriptors),
                                    "relative_year": 0
                                }
                                periods_dict[this_context_dict["context_id"]] = this_context_dict
                                
                    except ValueError:
                        logger.error(f"Could not compare dates: {context.period_instant} and {doc_period_end_date}")


        # 4. Prior Period Context (Annual)
        #periods_dict["PriorPeriodContext"] = None
        if doc_period_end_date_dt:
            for context_id, context in self.xbrl.contexts.items(): # Iterate ALL contexts for prior period context
                if context.period_start is not None and context.period_end is not None : # Still using descriptor filter for 'main' prior period context
                    period_start_dt = datetime.strptime(context.period_start, '%Y-%m-%d')
                    period_end_dt = datetime.strptime(context.period_end, '%Y-%m-%d')
                    if (period_end_dt - period_start_dt).days >= 360:
                        try:
                            if period_end_dt < doc_period_end_date_dt:
                                this_context_dict = {
                                    "context_id": context_id,
                                    "period_string": context.get_period_string(),
                                    "start_date": context.period_start,
                                    "end_date": context.period_end,
                                    "main_context": bool(not context.descriptors),
                                    "relative_year": 0
                                }
                                periods_dict[this_context_dict["context_id"]] = this_context_dict
                                #break # Assuming only one prior period context
                        except ValueError:
                            logger.error(f"Could not compare dates: {context.period_end} and {doc_period_end_date}")

        # logger.debug("-"*80)
        # logger.debug("instance.identify_reporting_contexts() output: <periods_dict>")
        # _items = 0
        # for context_id, context_dict in periods_dict.items():
        #     if "2019-01-01/2019-12-31" in context_dict["period_string"] :
        #         _items += 1
        #         logger.debug("-"*80)
        #         logger.debug(context_id)
        #         for key, value in context_dict.items():
        #             logger.debug(f"{context_id}--{key}: {value}")  
        #         if _items > 3:
        #             break

        return periods_dict
