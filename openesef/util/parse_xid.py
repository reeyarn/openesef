
import datetime
#from openesef.util import util_mylogger
from openesef.util.util_mylogger import setup_logger #util_mylogger


#import openesef
from openesef.base import pool, const
from openesef.engines import tax_reporter
from openesef.edgar.edgar import EG_LOCAL
from openesef.edgar.filing import Filing

from openesef.base.pool import Pool

from openesef.taxonomy.taxonomy import Taxonomy
from openesef.instance.instance import Instance


from lxml import etree as lxml_etree
from io import StringIO, BytesIO



import fs
import os
import re
import gzip
import pathlib
import pandas as pd
import logging
#logging.basicConfig(level=logging.DEBUG)
from itertools import chain
##openesef.base.pool.logger.setLevel(logging.INFO)
#openesef.taxonomy.taxonomy.logger.setLevel(logging.INFO)
#openesef.engines.tax_reporter.logger.setLevel(logging.INFO)
import traceback
import io
#traceback.print_exc(limit=10)

import logging 
if __name__=="__main__":
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/", full_format=True)
else:
    logger = logging.getLogger("openesef.util.parse_concepts") 

from openesef.util.parse_concepts import get_presentation_networks, get_network_details
#from openesef.util.parse_concepts import ins_facts #, yield_concept_tree
from itertools import chain
import pandas as pd
import logging

# Helper function to yield concept tree - reimplemented for new presentation structure
def yield_concept_tree(concept_dict, parent_dict=None):
    """
    Recursively yield concepts from a presentation hierarchy structure
    with proper order preservation
    """
    # First yield the current concept with explicit order handling
    order_value = concept_dict.get("order")
    
    # For debugging
    if order_value is not None:
        print(f"Found order value: {order_value} for concept {concept_dict.get('to', '')}")
    
    concept_data = {
        "concept_name": concept_dict.get("name", ""),
        "concept_qname": concept_dict.get("to", ""),
        "label": concept_dict.get("label", ""),
        "order": order_value,  # Explicitly use the extracted value
        "parent_qname": parent_dict.get("to") if parent_dict else None,
        "preferred_label": concept_dict.get("preferred_label", "")
    }
    yield concept_data
    
    # Then yield all children
    for child in concept_dict.get("children", []):
        yield from yield_concept_tree(child, concept_dict)

class TaxonomyPresentation:
    """Class to hold taxonomy presentation information"""
    
    def __init__(self, tax, reporter=None):
        logger.debug(f"Initializing TaxonomyPresentation with taxonomy containing {len(tax.concepts)} concepts")
        self.tax = tax  # Store the taxonomy object
        self.reporter = reporter
        self.concept_df = None
        self.allowed_segments_by_statement = {}
        self.concept_dict = {}  # Indexed by concept_qname for faster lookups
        
        # Process the taxonomy to extract concepts and structure
        self._process_taxonomy_direct()
        
        logger.debug(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        if len(self.concept_dict) == 0:
            logger.error("ERROR: No concepts were added to the concept dictionary!")
            self._process_all_concepts()  # Fallback if nothing else worked
    
    def _process_taxonomy_direct(self):
        """Extract presentation networks directly from taxonomy linkbases"""
        logger.debug("Directly processing taxonomy presentation linkbases")
        
        # Get all linkbases that might contain presentation information
        pres_linkbases = []
        
        # Method 1: Look for presentation linkbases by filename pattern
        for href, linkbase in self.tax.linkbases.items():
            if '_pre.xml' in href:
                logger.debug(f"Found presentation linkbase by pattern: {href}")
                pres_linkbases.append(linkbase)
        
        # Method 2: Use taxonomy's built-in methods to find presentation links if available
        if hasattr(self.tax, 'base_sets'):
            for key, base_set in self.tax.base_sets.items():
                if 'presentationArc' in key:
                    logger.debug(f"Found presentation base set: {key}")
                    if hasattr(base_set, 'roots') and base_set.roots:
                        for root in base_set.roots:
                            role = key.split('|')[-1] if '|' in key else 'UnknownRole'
                            statement_name = role.split('/')[-1] if '/' in role else role
                            logger.debug(f"Processing statement: {statement_name} with root {root.qname if hasattr(root, 'qname') else 'Unknown'}")
                            self._process_base_set_tree(base_set, root, statement_name)
        
        # If no presentation info found, try to use pres_linkbases if taxonomy has them
        if hasattr(self.tax, 'pres_linkbases') and not self.concept_dict:
            logger.debug(f"Using pres_linkbases from taxonomy: {len(self.tax.pres_linkbases)}")
            for plb in self.tax.pres_linkbases:
                self._process_presentation_linkbase(plb)
        
        # If still nothing found, look through linkbases manually
        if not self.concept_dict and self.reporter:
            logger.debug("Using reporter to extract presentation relationships")
            for href, linkbase in self.tax.linkbases.items():
                if '_pre.xml' in href:
                    self._process_linkbase_with_reporter(linkbase, href)
        
        # If still nothing, use the fallback method
        if not self.concept_dict:
            logger.warning("No presentation structure found. Using fallback method.")
            self._process_all_concepts()
    
    def _process_base_set_tree(self, base_set, root_concept, statement_name):
        """Process a presentation tree starting from a root concept"""
        logger.debug(f"Processing presentation tree for {statement_name}")
        
        # Initialize statement storage
        if statement_name not in self.allowed_segments_by_statement:
            self.allowed_segments_by_statement[statement_name] = {}
        
        # Process the root concept
        root_qname = root_concept.qname if hasattr(root_concept, 'qname') else str(root_concept)
        logger.debug(f"Root concept: {root_qname}")
        
        # Add root concept to dictionary
        if root_qname not in self.concept_dict:
            root_info = {
                "concept_name": root_concept.name if hasattr(root_concept, 'name') else root_qname.split(":")[-1],
                "concept_qname": root_qname,
                "label": root_concept.get_label() if hasattr(root_concept, 'get_label') else None,
                "order": 0,  # Root concept
                "statement_name": statement_name,
                "statement_label": statement_name,
            }
            self.concept_dict[root_qname] = root_info
        
        # Process children if this is a Network object with children_map
        if hasattr(base_set, 'children_map') and root_qname in base_set.children_map:
            children = base_set.children_map.get(root_qname, [])
            logger.debug(f"Found {len(children)} children for {root_qname}")
            
            for i, child_info in enumerate(children):
                child = child_info.to_concept if hasattr(child_info, 'to_concept') else child_info
                order = child_info.order if hasattr(child_info, 'order') else i * 10
                self._process_child_concept(child, root_qname, order, statement_name)
    
    def _process_child_concept(self, concept, parent_qname, order, statement_name):
        """Process a concept in the presentation tree"""
        concept_qname = concept.qname if hasattr(concept, 'qname') else str(concept)
        logger.debug(f"Processing child concept: {concept_qname} (parent: {parent_qname}, order: {order})")
        
        # Add concept to dictionary
        if concept_qname not in self.concept_dict:
            concept_info = {
                "concept_name": concept.name if hasattr(concept, 'name') else concept_qname.split(":")[-1],
                "concept_qname": concept_qname,
                "label": concept.get_label() if hasattr(concept, 'get_label') else None,
                "parent_qname": parent_qname,
                "order": order,
                "statement_name": statement_name,
                "statement_label": statement_name,
                "axis_type": None,
                "domain_type": None,
                "member_type": None,
            }
            
            # Set type indicators
            if 'Axis' in concept_qname:
                concept_info['axis_type'] = concept_qname
            if 'Domain' in concept_qname:
                concept_info['domain_type'] = concept_qname
            if 'Member' in concept_qname:
                concept_info['member_type'] = concept_qname
            
            self.concept_dict[concept_qname] = concept_info
            
            # Initialize allowed segments
            allowed_segments = self.allowed_segments_by_statement.get(statement_name, {})
            if concept_qname not in allowed_segments:
                allowed_segments[concept_qname] = [{}, {}]  # Allow empty segment by default
                self.allowed_segments_by_statement[statement_name] = allowed_segments
    
    def _process_presentation_linkbase(self, plb):
        """Process a presentation linkbase directly"""
        logger.debug(f"Processing presentation linkbase: {plb.location if hasattr(plb, 'location') else 'Unknown'}")
        
        # Extract presentation arcs if available
        if hasattr(plb, 'presentation_arcs'):
            for arc in plb.presentation_arcs:
                from_label = arc.from_label if hasattr(arc, 'from_label') else None
                to_label = arc.to_label if hasattr(arc, 'to_label') else None
                order = arc.order if hasattr(arc, 'order') else 0
                
                logger.debug(f"Found arc: {from_label} -> {to_label}, Order: {order}")
                
                # Lookup concepts if locators available
                if hasattr(plb, 'current_link') and hasattr(plb.current_link, 'locators'):
                    from_locator = plb.current_link.locators.get(from_label)
                    to_locator = plb.current_link.locators.get(to_label)
                    
                    if from_locator and to_locator:
                        from_href = from_locator.href if hasattr(from_locator, 'href') else None
                        to_href = to_locator.href if hasattr(to_locator, 'href') else None
                        
                        # Try to find concepts by HREF
                        from_concept = self.tax.concepts.get(from_href)
                        to_concept = self.tax.concepts.get(to_href)
                        
                        if from_concept and to_concept:
                            statement_name = "PresentationLinkbase"
                            if hasattr(plb, 'current_link') and hasattr(plb.current_link, 'role'):
                                statement_name = plb.current_link.role.split('/')[-1]
                            
                            # Add concepts to our dictionary
                            from_qname = from_concept.qname if hasattr(from_concept, 'qname') else str(from_concept)
                            to_qname = to_concept.qname if hasattr(to_concept, 'qname') else str(to_concept)
                            
                            self._process_child_concept(to_concept, from_qname, order, statement_name)
    
    def _process_linkbase_with_reporter(self, linkbase, href):
        """Process linkbase using taxonomy reporter if available"""
        logger.debug(f"Processing linkbase with reporter: {href}")
        
        if not self.reporter:
            return
        
        # Use reporter to get presentation networks
        if hasattr(self.reporter, 'get_networks_for_linkbase'):
            networks = self.reporter.get_networks_for_linkbase(linkbase)
            for network in networks:
                logger.debug(f"Found network in linkbase: {network.role if hasattr(network, 'role') else 'Unknown'}")
                
                statement_name = network.role.split('/')[-1] if hasattr(network, 'role') and network.role else "Unknown"
                
                # Try to access nodes through reporter
                if hasattr(self.reporter, 'get_network_tree'):
                    tree = self.reporter.get_network_tree(network)
                    self._process_network_tree(tree, statement_name)
    
    def _process_network_tree(self, tree, statement_name):
        """Process a network tree from reporter"""
        logger.debug(f"Processing network tree for {statement_name}")
        
        # Initialize statement storage
        if statement_name not in self.allowed_segments_by_statement:
            self.allowed_segments_by_statement[statement_name] = {}
        
        # Process tree nodes
        for node in tree:
            concept = node.concept if hasattr(node, 'concept') else None
            if not concept:
                continue
            
            concept_qname = concept.qname if hasattr(concept, 'qname') else str(concept)
            parent = node.parent.concept if hasattr(node, 'parent') and hasattr(node.parent, 'concept') else None
            parent_qname = parent.qname if parent and hasattr(parent, 'qname') else None
            order = node.order if hasattr(node, 'order') else 0
            
            # Add to dictionary
            if concept_qname not in self.concept_dict:
                self.concept_dict[concept_qname] = {
                    "concept_name": concept.name if hasattr(concept, 'name') else concept_qname.split(":")[-1],
                    "concept_qname": concept_qname,
                    "label": concept.get_label() if hasattr(concept, 'get_label') else None,
                    "parent_qname": parent_qname,
                    "order": order,
                    "statement_name": statement_name,
                    "statement_label": statement_name
                }
            
            # Initialize allowed segments
            allowed_segments = self.allowed_segments_by_statement.get(statement_name, {})
            if concept_qname not in allowed_segments:
                allowed_segments[concept_qname] = [{}, {}]  # Allow empty segment by default
                self.allowed_segments_by_statement[statement_name] = allowed_segments
    
    def _process_all_concepts(self):
        """Fallback method to process all concepts in taxonomy"""
        logger.info("Processing all concepts from taxonomy (fallback)")
        
        # Create a minimal allowed_segments structure
        default_statement = "AllConcepts"
        self.allowed_segments_by_statement[default_statement] = {}
        
        # Add all concepts from taxonomy
        for qname, concept in self.tax.concepts_by_qname.items():
            concept_qname_str = str(qname)
            self.concept_dict[concept_qname_str] = {
                "concept_name": concept.name,
                "concept_qname": concept_qname_str,
                "label": concept.get_label() if hasattr(concept, 'get_label') else None,
                "order": None,  # No order information available
                "statement_name": default_statement,
                "statement_label": default_statement
            }
            
            # Allow this concept in the default statement
            self.allowed_segments_by_statement[default_statement][concept_qname_str] = [{}, {}]  # Empty segment
        
        logger.info(f"Added {len(self.concept_dict)} concepts from taxonomy using fallback")
        
        # Create a minimal DataFrame
        if self.concept_dict:
            self.concept_df = pd.DataFrame.from_records(list(self.concept_dict.values()))
    
    # The rest of the methods remain unchanged
    def is_valid_concept(self, concept_qname):
        """Check if a concept is in the presentation"""
        concept_qname_str = str(concept_qname)
        result = concept_qname_str in self.concept_dict
        
        if not result and ':' not in concept_qname_str:
            for prefix in ['us-gaap:', 'ifrs:', 'dei:']:
                prefixed_qname = f"{prefix}{concept_qname_str}"
                if prefixed_qname in self.concept_dict:
                    return True
        
        return result
    
    def get_concept_info(self, concept_qname):
        """Get information about a concept"""
        return self.concept_dict.get(concept_qname)
    
    def is_valid_segment(self, concept_qname, segment_data, statement_name=None):
        """Check if a segment is valid for a concept"""
        if statement_name:
            # Check only in the specified statement
            allowed_segments = self.allowed_segments_by_statement.get(statement_name, {}).get(concept_qname, [])
            return segment_data in allowed_segments
        else:
            # Check in all statements
            for statement, allowed_segments_by_concept in self.allowed_segments_by_statement.items():
                if concept_qname in allowed_segments_by_concept:
                    allowed_segments = allowed_segments_by_concept[concept_qname]
                    if segment_data in allowed_segments:
                        return True
            
            return False

def ins_facts(xid, tax, tax_presentation, periods_dict):
    """Extract facts from instance"""
    logger.debug(f"Starting fact extraction with {len(xid.xbrl.facts)} facts and {len(periods_dict)} valid contexts")
    
    valid_context_ids = list(periods_dict.keys())
    logger.debug(f"Valid context IDs: {valid_context_ids[:5]}..." if len(valid_context_ids) > 5 else f"Valid context IDs: {valid_context_ids}")
    
    fact_list = []
    included_count = 0
    excluded_count = 0
    invalid_concept_count = 0
    invalid_context_count = 0

    for key, fact in xid.xbrl.facts.items():
        concept = tax.concepts_by_qname.get(fact.qname)
        
        # Skip if concept not found in taxonomy
        if not concept:
            logger.debug(f"Fact {key}: Concept {fact.qname} not found in taxonomy")
            continue
            
        concept_qname = str(concept.qname)
        
        # Check if concept is valid in presentation
        if not tax_presentation.is_valid_concept(concept_qname):
            invalid_concept_count += 1
            if invalid_concept_count <= 10:  # Limit logging to avoid excessive output
                logger.debug(f"Fact {key}: Concept {concept_qname} not in presentation")
            continue
            
        # Check if context is valid
        if fact.context_ref not in valid_context_ids:
            invalid_context_count += 1
            if invalid_context_count <= 10:  # Limit logging
                logger.debug(f"Fact {key}: Context {fact.context_ref} not in valid contexts")
            continue
            
        # Get context information
        ref_context = xid.xbrl.contexts.get(fact.context_ref)
        this_context_dict = periods_dict[fact.context_ref]
        
        # Extract segment data
        segment_data = {}
        if ref_context and ref_context.segment:
            for dimension, member in ref_context.segment.items():
                segment_data[str(dimension)] = member.text if hasattr(member, 'text') else str(member)
            logger.debug(f"Fact {key}: Has segment data: {segment_data}")
        
        # Check if segment is valid for this concept and identify the statement
        fact_included = False
        statement_names = []
        
        for statement_name, allowed_segments_by_concept in tax_presentation.allowed_segments_by_statement.items():
            if concept_qname in allowed_segments_by_concept:
                allowed_segments = allowed_segments_by_concept[concept_qname]
                if segment_data in allowed_segments:
                    fact_included = True
                    statement_names.append(statement_name)
        
        # Get concept info for additional details
        concept_info = tax_presentation.get_concept_info(concept_qname) or {}

        # Debug the order value in concept_info
        if 'order' in concept_info:
            logger.debug(f"Concept {concept_qname} has order {concept_info['order']}")

        
        if fact_included:
            included_count += 1
            if included_count <= 20:  # Limit logging
                logger.debug(f"Fact {key}: INCLUDED - Concept: {concept_qname}, Context: {fact.context_ref}")
                logger.debug(f"  Statements: {statement_names}")
                if fact.value:
                    logger.debug(f"  Fact Value: {fact.value[:30]}...")
        else:
            excluded_count += 1
            if excluded_count <= 20:  # Limit logging
                logger.debug(f"Fact {key}: EXCLUDED - Concept: {concept_qname}, Context: {fact.context_ref}, Segment: {segment_data}")
        
        # Create fact data dictionary with enhanced information
        fact_data = {
            # Basic fact information
            'concept_name': concept.name,
            'concept_qname': concept_qname,
            'value': fact.value if "text" not in concept.name.lower() else fact.value[:100],
            'context_ref': fact.context_ref,
            
            # Context information
            'period_string': this_context_dict.get("period_string", None),
            'period_type': 'instant' if ref_context and ref_context.period_instant else 'duration',
            'period_start': ref_context.period_start if ref_context else None,
            'period_end': ref_context.period_end if ref_context else None,
            'period_instant': ref_context.period_instant if ref_context else None,
            'entity_scheme': this_context_dict.get("entity_scheme", None),
            'entity_identifier': this_context_dict.get("entity_identifier", None),
            
            # Segment information
            'segment': segment_data,
            'segment_data': segment_data,
            'has_dimensions': bool(segment_data),
            'dimension_count': len(segment_data) if segment_data else 0,
            'scenario': this_context_dict.get("scenario", None),
            
            # Statement information
            'statement_names': ';'.join(statement_names),
            'primary_statement': statement_names[0] if statement_names else None,
            'appears_in_statements': len(statement_names),
            
            # Concept metadata from presentation
            'statement_label': concept_info.get('statement_label', None),
            'parent_qname': concept_info.get('parent_qname', None),
            'label': concept_info.get('label', None),
            'order': concept_info.get('order', None),
            
            # Inclusion flag
            'fact_included': fact_included
        }
        fact_list.append(fact_data)

    # Create DataFrame from collected facts
    fact_df = pd.DataFrame.from_records(fact_list)
    
    # Log summary statistics
    logger.debug(f"Fact extraction complete:")
    logger.debug(f"  Total facts processed: {len(xid.xbrl.facts)}")
    logger.debug(f"  Facts included: {included_count}")
    logger.debug(f"  Facts excluded: {excluded_count}")
    logger.debug(f"  Invalid concepts: {invalid_concept_count}")
    logger.debug(f"  Invalid contexts: {invalid_context_count}")
    logger.debug(f"  Final DataFrame size: {len(fact_df)} rows")
    
    # Log statement distribution
    if not fact_df.empty and 'primary_statement' in fact_df.columns:
        statement_counts = fact_df['primary_statement'].value_counts()
        logger.debug("Statement distribution in extracted facts:")
        for statement, count in statement_counts.items():
            if statement:  # Skip None values
                logger.debug(f"  {statement}: {count} facts")
    
    # Log period distribution
    if not fact_df.empty and 'period_string' in fact_df.columns:
        period_counts = fact_df['period_string'].value_counts()
        logger.debug("Period distribution in extracted facts:")
        for period, count in period_counts.items():
            logger.debug(f"  {period}: {count} facts")

    if not fact_df.empty:
        logger.debug(f"Order value counts in fact_df: {fact_df['order'].value_counts().to_dict()}")
    
    return fact_df


if __name__ == "__main__": # EDGAR iXBRL example
    from openesef.edgar.loader import load_xbrl_filing
    xid, tax = load_xbrl_filing(ticker="TSLA", year=2020)
    logger.debug("\n\n================ FINISHED LOADING XBRL FILEING =================\n\n")
    
    # Make sure the presentation linkbases are loaded
    if not hasattr(tax, 'pres_linkbases'):
        tax.load_presentation_linkbases()
        
    reporter = tax_reporter.TaxonomyReporter(tax)
    periods_dict = xid.identify_reporting_contexts()

    tax_presentation = TaxonomyPresentation(tax, reporter)
    so_names = [sn for sn in tax_presentation.allowed_segments_by_statement.keys() if "operations" in sn.lower()]
    so_name = so_names[0] if so_names else None
    logger.debug(f"Name <Statement of Operations>: {so_name}")
    fact_df = ins_facts(xid, tax, tax_presentation, periods_dict)        