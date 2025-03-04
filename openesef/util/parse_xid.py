
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


from openesef.util.parse_concepts import ins_facts #, yield_concept_tree
from itertools import chain
import pandas as pd
import logging

# Helper function to yield concept tree - reimplemented for new presentation structure
def yield_concept_tree(concept_dict, parent_dict=None):
    """
    Recursively yield concepts from a presentation hierarchy structure
    """
    # First yield the current concept
    concept_data = {
        "concept_name": concept_dict.get("name", ""),
        "concept_qname": concept_dict.get("to", ""),
        "label": concept_dict.get("label", ""),
        "order": concept_dict.get("order", 0),
        "parent_qname": parent_dict.get("to") if parent_dict else None,
        "preferred_label": concept_dict.get("preferred_label", "")
    }
    
    yield concept_data
    
    # Then yield all children
    for child in concept_dict.get("children", []):
        yield from yield_concept_tree(child, concept_dict)

class TaxonomyPresentation:
    """Class to hold taxonomy presentation information using new presentation linkbase implementation"""
    
    def __init__(self, tax, reporter=None):
        logger.debug(f"Initializing TaxonomyPresentation with taxonomy containing {len(tax.concepts)} concepts")
        self.tax = tax  # Store the taxonomy object
        self.concept_df = None
        self.allowed_segments_by_statement = {}
        self.concept_dict = {}  # Indexed by concept_qname for faster lookups
        
        # Ensure presentation linkbases are loaded
        if not hasattr(tax, 'pres_linkbases'):
            tax.load_presentation_linkbases()
            
        self._process_taxonomy()
        
        logger.debug(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        if len(self.concept_dict) == 0:
            logger.error("ERROR: No concepts were added to the concept dictionary!")
        else:
            sample_concepts = list(self.concept_dict.keys())[:10]
            logger.debug(f"Sample concepts in dictionary: {sample_concepts}")
    
    def _process_taxonomy(self):
        """Extract presentation networks from taxonomy using new presentation linkbase implementation"""
        logger.debug("Processing taxonomy presentation linkbases")
        
        # Check if presentation linkbases are loaded
        if not hasattr(self.tax, 'pres_linkbases'):
            logger.warning("No presentation linkbases found in taxonomy. Loading now...")
            self.tax.load_presentation_linkbases()
        
        # Get presentation linkbases
        pres_linkbases = getattr(self.tax, 'pres_linkbases', [])
        logger.debug(f"Found {len(pres_linkbases)} presentation linkbases")
        
        # If no linkbases found, try to get all concepts from taxonomy
        if not pres_linkbases:
            logger.warning("No presentation linkbases available. Adding all concepts from taxonomy.")
            for qname, concept in self.tax.concepts_by_qname.items():
                concept_qname_str = str(qname)
                self.concept_dict[concept_qname_str] = {
                    "concept_name": concept.name,
                    "concept_qname": concept_qname_str,
                    "label": concept.get_label() if hasattr(concept, 'get_label') else None
                }
            logger.debug(f"Added {len(self.concept_dict)} concepts from taxonomy")
            return
        
        concepts_by_statement = {}
        allowed_segments_by_statement = {}
        
        # Track processed concepts to avoid duplication
        processed_concepts = set()
        
        # Process each linkbase
        for plb in pres_linkbases:
            # Get the presentation hierarchy from the linkbase
            presentation_hierarchy = plb.get_presentation_hierarchy()
            
            # Each top-level parent is a statement or statement section
            for parent_concept, children in presentation_hierarchy.items():
                # Use the role as the statement name if available, otherwise use parent concept
                role_uri = plb.current_link.role if hasattr(plb, 'current_link') and hasattr(plb.current_link, 'role') else ""
                statement_name = role_uri.split('/')[-1] if role_uri else parent_concept
                
                logger.debug("-"*80)
                logger.debug(f"Processing statement: {statement_name}")
                
                # Prepare to store concepts for this statement
                if statement_name not in concepts_by_statement:
                    concepts_by_statement[statement_name] = []
                    allowed_segments_by_statement[statement_name] = {}
                
                # First, add the parent concept itself
                parent_info = {
                    "to": parent_concept,
                    "name": parent_concept.split("_")[-1] if "_" in parent_concept else parent_concept,
                    "label": self.tax.get_concept_label(parent_concept) if hasattr(self.tax, 'get_concept_label') else parent_concept,
                    "children": []
                }
                concepts_by_statement[statement_name].append(parent_info)
                
                # First pass: create tree structure from flat hierarchy
                concept_tree = {}
                concept_tree[parent_concept] = parent_info
                
                # Build tree structure and track axis/members
                axis_member_map = {}
                
                for child in children:
                    child_concept = child['to']
                    order = child['order']
                    preferred_label = child.get('preferred_label', '')
                    
                    # Find or create the concept in our tree
                    if child_concept not in concept_tree:
                        concept_tree[child_concept] = {
                            "to": child_concept,
                            "name": child_concept.split("_")[-1] if "_" in child_concept else child_concept,
                            "label": self.tax.get_concept_label(child_concept) if hasattr(self.tax, 'get_concept_label') else child_concept,
                            "order": order,
                            "preferred_label": preferred_label,
                            "children": []
                        }
                    
                    # Add as child to parent
                    concept_tree[parent_concept]["children"].append(concept_tree[child_concept])
                    
                    # Track axis-member relationships
                    if 'Axis' in child_concept:
                        if child_concept not in axis_member_map:
                            axis_member_map[child_concept] = set()
                    elif 'Member' in child_concept and parent_concept and 'Axis' in parent_concept:
                        axis_member_map[parent_concept].add(child_concept)
                    
                    # Add this concept to processed set
                    if child_concept not in processed_concepts:
                        processed_concepts.add(child_concept)
                        
                        # Initialize allowed segments for this concept
                        allowed_segments = allowed_segments_by_statement[statement_name]
                        if child_concept not in allowed_segments:
                            allowed_segments[child_concept] = set()
                            allowed_segments[child_concept].add(frozenset())  # Empty segment for totals
                
                # Second pass: build allowed segments
                for concept_qname in allowed_segments_by_statement[statement_name].keys():
                    # Skip axes, members, and domains for segment building
                    if any(x in concept_qname for x in ['Axis', 'Member', 'Domain']):
                        continue
                    
                    # For each axis in the network
                    for axis, members in axis_member_map.items():
                        for member in members:
                            # Associate this member with the concept under the current axis
                            allowed_segments_by_statement[statement_name][concept_qname].add(
                                frozenset({axis: member}.items())
                            )
        
        # Build concept DataFrame from the tree
        concept_tree_list = []
        
        for statement, statement_concepts in concepts_by_statement.items():
            statement_concept = statement_concepts[0]
            this_statement_list = []
            
            # Track processed concepts within this statement to avoid duplication
            statement_processed = set()
            
            for concept in statement_concepts:
                this_concept_generator = yield_concept_tree(concept)
                for this_concept_dict in this_concept_generator:
                    concept_qname = str(this_concept_dict['concept_qname'])
                    
                    # Skip if already processed in this statement
                    if concept_qname in statement_processed:
                        continue
                    statement_processed.add(concept_qname)
                    
                    # Preserve all original fields
                    this_concept_dict['statement_label'] = statement_concept.get("label")
                    this_concept_dict['statement_name'] = statement
                    this_concept_dict['axis_type'] = None
                    this_concept_dict['domain_type'] = None
                    this_concept_dict['member_type'] = None
                    
                    # Make sure we keep the order and label
                    if 'order' not in this_concept_dict:
                        this_concept_dict['order'] = None
                    if 'label' not in this_concept_dict:
                        # Try to get label from reporter if not already present
                        this_concept_dict['label'] = self.tax.get_concept_label(concept_qname) if hasattr(self.tax, 'get_concept_label') else None
                    
                    if 'Axis' in concept_qname:
                        this_concept_dict['axis_type'] = concept_qname
                    if 'Domain' in concept_qname:
                        this_concept_dict['domain_type'] = concept_qname
                    if 'Member' in concept_qname:
                        this_concept_dict['member_type'] = concept_qname
                        
                    this_statement_list.append(this_concept_dict)
            concept_tree_list.append(this_statement_list)
        
        concept_tree_list = list(chain.from_iterable(concept_tree_list))
        self.concept_df = pd.DataFrame.from_records(concept_tree_list)
        self.concept_df = self.concept_df.drop_duplicates(subset=["concept_qname"]).reset_index(drop=True)
        logger.debug(f"Created concept DataFrame with {len(self.concept_df)} unique concepts")

        # Convert frozenset to regular dict for better readability in logs
        for statement_name, allowed_segments_by_concept in allowed_segments_by_statement.items():
            self.allowed_segments_by_statement[statement_name] = {
                concept: [dict(segment) for segment in segments]
                for concept, segments in allowed_segments_by_concept.items()
            }
            
        # After building the concept DataFrame, ensure we populate the concept_dict
        if self.concept_df is not None and not self.concept_df.empty:
            for _, row in self.concept_df.iterrows():
                self.concept_dict[row['concept_qname']] = row.to_dict()
            logger.debug(f"Built concept dictionary with {len(self.concept_dict)} entries from DataFrame")
        else:
            logger.error("Failed to build concept DataFrame")
            
            # Fallback: add all concepts from taxonomy
            for qname, concept in self.tax.concepts_by_qname.items():
                concept_qname_str = str(qname)
                self.concept_dict[concept_qname_str] = {
                    "concept_name": concept.name,
                    "concept_qname": concept_qname_str,
                    "label": concept.get_label() if hasattr(concept, 'get_label') else None
                }
            logger.debug(f"Fallback: Added {len(self.concept_dict)} concepts from taxonomy")

    # The rest of the TaxonomyPresentation class remains unchanged
    def is_valid_concept(self, concept_qname):
        """Check if a concept is in the presentation"""
        # Convert to string if it's not already
        concept_qname_str = str(concept_qname)
        
        # Debug output
        result = concept_qname_str in self.concept_dict
        logger.debug(f"Checking if concept '{concept_qname_str}' is valid: {result}")
        
        # If not found, check if we need to add a prefix
        if not result and ':' not in concept_qname_str:
            # Try with common prefixes
            for prefix in ['us-gaap:', 'ifrs:', 'dei:']:
                prefixed_qname = f"{prefix}{concept_qname_str}"
                if prefixed_qname in self.concept_dict:
                    logger.debug(f"  Found with prefix: {prefixed_qname}")
                    return True
        
        return result
    
    def get_concept_info(self, concept_qname):
        """Get information about a concept"""
        info = self.concept_dict.get(concept_qname)
        if info:
            logger.debug(f"Retrieved info for concept '{concept_qname}': statement={info.get('statement_name')}")
        else:
            logger.debug(f"No info found for concept '{concept_qname}'")
        return info
    
    def is_valid_segment(self, concept_qname, segment_data, statement_name=None):
        """Check if a segment is valid for a concept"""
        logger.debug(f"Checking if segment {segment_data} is valid for concept '{concept_qname}'")
        
        if statement_name:
            # Check only in the specified statement
            allowed_segments = self.allowed_segments_by_statement.get(statement_name, {}).get(concept_qname, [])
            result = segment_data in allowed_segments
            logger.debug(f"  In statement '{statement_name}': {result}")
            return result
        else:
            # Check in all statements
            for statement, allowed_segments_by_concept in self.allowed_segments_by_statement.items():
                if concept_qname in allowed_segments_by_concept:
                    allowed_segments = allowed_segments_by_concept[concept_qname]
                    if segment_data in allowed_segments:
                        logger.debug(f"  Valid in statement '{statement}'")
                        return True
            
            logger.debug(f"  Not valid in any statement")
            return False        

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