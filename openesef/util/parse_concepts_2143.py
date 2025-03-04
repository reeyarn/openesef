"""
https://devv.ai/search?threadId=echbdlppi9z4
"""

import sys

#sys.path = [p for p in sys.path if 'openesef' not in p] # Remove any existing openesef paths
#sys.path.insert(0, "./openesef")  # if you're in the same directory as parse_concepts.py


import datetime
#from openesef.util import util_mylogger
from openesef.util.util_mylogger import setup_logger #util_mylogger


#import openesef
from openesef.base import pool, const
from openesef.engines import tax_reporter
from openesef.edgar.edgar import EG_LOCAL
from openesef.edgar.filing import Filing
from openesef.taxonomy.xlink import XLink
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
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/", full_format=True, formatter_string='%(name)s.%(levelname)s: %(message)s',pid=0)
else:
    logger = logging.getLogger("openesef.util.parse_concepts") 


def ungzip_file(gzip_path, output_path):
    if not os.path.exists(output_path):
        with gzip.open(gzip_path, 'rb') as f_in:
            with open(output_path, 'wb') as f_out:
                f_out.write(f_in.read())

def prepare_files(full_instance_zip_path, location_path):
    """Prepare files with ESEF structure awareness"""
    # Ungzip files if needed
    if os.path.exists(full_instance_zip_path):
        instance_file = full_instance_zip_path
        if full_instance_zip_path.endswith('.gzip'):
            ungzipped_file = full_instance_zip_path[:-5]
            ungzip_file(full_instance_zip_path, ungzipped_file)
            instance_file = ungzipped_file
        
        # Handle GZIP files in the ESEF structure
        for root, _, files in os.walk(location_path):
            for file in files:
                if file.endswith('.gzip'):
                    ungzipped_file = os.path.join(root, file[:-5])
                    ungzip_file(os.path.join(root, file), ungzipped_file)
        
        return instance_file



def get_network_concepts(reporter, network):
    """Get all concepts in a network using the reporter"""
    # Get the arc name, role, and arcrole from the network
    arc_name = network.arc_name
    role = network.role
    arcrole = network.arcrole
    
    # Use r_base_set to get the network details
    reporter.r_base_set(arc_name, role, arcrole)
    
    # Get all nodes in the network
    nodes = reporter.taxonomy.get_bs_members(arc_name, role, arcrole)
    
    # Create a hierarchy
    concepts_by_level = {}
    for node in nodes:
        level = node.Level
        if level not in concepts_by_level:
            concepts_by_level[level] = []
        
        concept_info = {
            'name': str(node.Concept.qname) if hasattr(node.Concept, 'qname') else str(node.Concept),
            'label': node.Concept.get_label() if hasattr(node.Concept, 'get_label') else 'N/A',
            'period_type': node.Concept.period_type if hasattr(node.Concept, 'period_type') else 'N/A',
            'balance': node.Concept.balance if hasattr(node.Concept, 'balance') else 'N/A',
            'level': level,
            'children': []
        }
        concepts_by_level[level].append(concept_info)
    
    # Build the hierarchy from bottom up
    max_level = max(concepts_by_level.keys()) if concepts_by_level else 0
    for level in range(max_level, 0, -1):
        current_level_concepts = concepts_by_level.get(level, [])
        parent_level_concepts = concepts_by_level.get(level - 1, [])
        
        # Add current level concepts as children to their parents
        for parent in parent_level_concepts:
            parent['children'].extend([c for c in current_level_concepts])
    
    # Return root level concepts (level 0)
    return concepts_by_level.get(0, [])

def get_presentation_networks(taxonomy):
    """Get presentation networks from taxonomy"""
    logger.info("\nAccessing presentation networks...")
    
    # First check if presentation linkbases are loaded
    presentation_linkbases = []
    for lb_location, lb in taxonomy.linkbases.items():
        # Check if this is a presentation linkbase by looking at the file name
        if '_pre.xml' in lb_location.lower():
            logger.info(f"Found presentation linkbase: {lb_location}")
            # Debug information about the linkbase
            logger.info(f"Linkbase type: {type(lb)}, attributes: {dir(lb)}")
            if hasattr(lb, 'links'):
                logger.info(f"Number of links: {len(lb.links)}")
                for link in lb.links:
                    logger.debug(f"Link type: {type(link)}, tag: {getattr(link, 'tag', 'No tag')}")
            presentation_linkbases.append(lb)
    
    logger.info(f"Found {len(presentation_linkbases)} presentation linkbases")
    
    # Check if the taxonomy object has base_sets
    if hasattr(taxonomy, 'base_sets'):
        logger.info(f"Number of base_sets: {len(taxonomy.base_sets)}")
        
        presentation_networks = []
        # First try to get networks from base_sets
        for key, base_set in taxonomy.base_sets.items():
            if isinstance(key, tuple) and len(key) >= 3:
                arc_name, role, arcrole = key
                if 'presentation' in str(arc_name).lower():
                    logger.debug(f"Found presentation base_set: {key}")
                    presentation_networks.append(base_set)
            elif isinstance(key, str) and 'presentation' in key.lower():
                logger.info(f"Found presentation base_set: {key}")
                presentation_networks.append(base_set)
        
        if not presentation_networks:
            logger.warning("No presentation networks found in base_sets")
            
            # Try to build networks from presentation linkbases
            if presentation_linkbases:
                logger.info("Building networks from presentation linkbases...")
                for lb in presentation_linkbases:
                    if hasattr(lb, 'links'):
                        for link in lb.links:
                            # Add the link itself as a network
                            if 'presentation' in str(getattr(link, 'tag', '')).lower():
                                presentation_networks.append(link)
                                logger.info("Added presentation link to networks")
                            
                            # Also add any presentation arcs
                            if hasattr(link, 'arcs'):
                                for arc in link.arcs:
                                    if 'presentation' in str(getattr(arc, 'tag', '')).lower():
                                        presentation_networks.append(arc)
                                        logger.info("Added presentation arc to networks")
                
                if presentation_networks:
                    logger.info(f"Built {len(presentation_networks)} networks from linkbases")
                    return presentation_networks
            
            # If still no networks, try compilation
            if hasattr(taxonomy, 'compile_presentation_networks'):
                logger.info("Attempting to compile presentation networks...")
                networks = taxonomy.compile_presentation_networks()
                if networks:
                    logger.info(f"Compilation yielded {len(networks)} networks")
                    return networks
        
        return presentation_networks
    else:
        logger.error("No base_sets found in taxonomy")
        return []


def print_concept_tree(concept, level=0):
    """Print concept hierarchy with indentation"""
    indent = "  " * level
    logger.info(f"{indent}Concept: {concept['name']}")
    logger.info(f"{indent}Label: {concept['label']}")
    logger.info(f"{indent}Period Type: {concept['period_type']}")
    logger.info(f"{indent}Balance: {concept['balance']}")
    logger.info(f"{indent}Level: {concept.get('level', 'N/A')}")
    logger.info(f"{indent}" + "-" * 40)
    
    # Print children recursively
    for child in concept.get('children', []):
        print_concept_tree(child, level + 1)

def yield_concept_tree(concept_dict):
    """
    Yield concept and its children as a flat list
    """
    # First yield the concept itself
    yield {
        "concept_name": concept_dict["name"],
        "concept_qname": concept_dict["qname"],
        "parent_qname": concept_dict.get("parent_qname"),
        "grandparent_qname": concept_dict.get("grandparent_qname"),
        "label": concept_dict.get("label"),
        "order": concept_dict.get("order")
    }


def print_concepts_by_statement(concepts_by_statement):
    if not concepts_by_statement:
        logger.info("\nNo concepts found in the presentation linkbase")
        return

    for statement, concepts in concepts_by_statement.items():
        logger.info(f"\n=== {statement} ===")
        logger.info("=" * 80)
        for concept in concepts:
            print_concept_tree(concept)

def get_df_from_concepts_by_statement(concepts_by_statement):
    concept_tree_list = []
    if not concepts_by_statement:
        logger.info("\nNo concepts found in the presentation linkbase")
        return

    for statement, concepts in concepts_by_statement.items():
        for concept in concepts:
            concept_tree_list.append(yield_concept_tree(concept))

    df = pd.DataFrame(concept_tree_list)
    return df


def get_child_concepts(reporter, network, concept, taxonomy, visited=None):
    """Recursively get all child concepts of a given concept"""
    if visited is None:
        visited = set()

    # Get concept identifier (name or qname)
    concept_id = str(concept.qname) if hasattr(concept, 'qname') else str(concept)

    # Avoid circular references
    if concept_id in visited:
        return []
    
    visited.add(concept_id)
    children = []

    # Get all members from the network
    members = network.get_members(start_concept=concept, include_head=False)
    
    # Process each member
    for member in members:
        member_id = str(member.Concept.qname) if hasattr(member.Concept, 'qname') else str(member.Concept)
        if member_id not in visited:
            child_info = {
                'name': member_id,
                'label': member.Concept.get_label() if hasattr(member.Concept, 'get_label') else 'N/A',
                'period_type': member.Concept.period_type if hasattr(member.Concept, 'period_type') else 'N/A',
                'balance': member.Concept.balance if hasattr(member.Concept, 'balance') else 'N/A',
                'level': member.Level if hasattr(member, 'Level') else 'N/A',
                'children': get_child_concepts(reporter, network, member.Concept, taxonomy, visited)
            }
            children.append(child_info)
    
    return children

    # Compile the network using the reporter
    reporter.compile_network(network)
    
    # Get the network layout
    layout = reporter.get_network_layout(network)
    if layout:
        # Find children in the layout
        for item in layout:
            if item.Parent == concept and item.Concept not in visited:
                child_info = {
                    'name': str(item.Concept.qname) if hasattr(item.Concept, 'qname') else str(item.Concept),
                    'label': reporter.get_concept_label(item.Concept),
                    'period_type': item.Concept.period_type if hasattr(item.Concept, 'period_type') else 'N/A',
                    'balance': item.Concept.balance if hasattr(item.Concept, 'balance') else 'N/A',
                    'level': item.Level,
                    'children': get_child_concepts(reporter, network, item.Concept, taxonomy, visited)
                }
                children.append(child_info)
    
    return children


def print_concepts_by_statement(concepts_by_statement):
    if not concepts_by_statement:
        print("\nNo concepts found in the presentation linkbase")
        return
    
    for statement, concepts in concepts_by_statement.items():
        print(f"\n=== {statement} ===")
        print("-" * 80)
        for concept in concepts:
            print(f"Concept: {concept['name']}")
            print(f"Label: {concept['label']}")
            print(f"Period Type: {concept['period_type']}")
            print(f"Balance: {concept['balance']}")
            print("-" * 40)



def process_children_alt(relationships, parent, concepts, grandparent_qname, statement_name=None, statement_role=None):
    """
    Alternative recursive function to process children using relationships list
    """
    # Find children of this parent
    children = []
    for rel in relationships:
        if (hasattr(rel, 'source') and rel.source == parent) or \
           (hasattr(rel, 'from_') and rel.from_ == parent):
            child = rel.target if hasattr(rel, 'target') else rel.to
            children.append((child, rel))
    
    for child, rel in children:
        # Get order and preferred label
        order = getattr(rel, 'order', None)
        if order is None:
            order = getattr(rel, 'weight', None)
        if order is None:
            order = getattr(rel, 'priority', None)
            
        preferred_label = getattr(rel, 'preferred_label', None)
        
        # Get label
        if preferred_label and hasattr(child, 'get_label'):
            label = child.get_label(role=preferred_label)
        else:
            label = child.get_label() if hasattr(child, 'get_label') else None
        
        child_dict = {
            "name": child.name if hasattr(child, 'name') else str(child),
            "qname": child.qname if hasattr(child, 'qname') else str(child),
            "label": label,
            "order": order,
            "parent_qname": parent.qname if hasattr(parent, 'qname') else str(parent),
            "grandparent_qname": grandparent_qname,
            "statement_name": statement_name,  # Add statement name
            "statement_role": statement_role  # Add statement role
        }
        concepts.append(child_dict)
        
        # Continue recursion
        process_children_alt(relationships, child, concepts, parent.qname, statement_name, statement_role)

def get_network_details(tax, network):
    """Extract concept details from a presentation network"""
    concepts = []
    statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
    logger.info(f"Processing network {statement_name} with {len(network.relationships) if hasattr(network, 'relationships') else 0} relationships")
    
    try:
        if isinstance(network, XLink):
            logger.info("Processing XLink network")
            # Debug the network structure
            logger.debug(f"Network has locators: {len(network.locators) if hasattr(network, 'locators') else 0}")
            logger.debug(f"Network has arcs: {len(network.arcs) if hasattr(network, 'arcs') else 0}")
            logger.debug(f"Network has resources: {len(network.resources) if hasattr(network, 'resources') else 0}")
            
            # Track processed concepts to avoid duplicates
            processed_concepts = set()
            
            # Process relationships to build concept list
            for rel in relationships:
                to_concept = rel['to']
                from_concept = rel['from']
                
                for concept in [to_concept, from_concept]:
                    concept_qname = str(concept.qname)
                    if concept_qname not in processed_concepts:
                        processed_concepts.add(concept_qname)
                        logger.debug(f"Processing concept {concept_qname}")
                        logger.debug(f"Concept has labels: {hasattr(concept, 'labels')}")
                        logger.debug(f"Concept object ID: {id(concept)}")
                        if hasattr(concept, 'labels'):
                            logger.debug(f"Available labels: {concept.labels}")
                        label = concept.get_label() if hasattr(concept, 'get_label') else 'N/A'
                        concept_info = {
                            'name': concept.name,
                            'qname': concept_qname,
                            'label': label,
                            'order': rel['order'],
                            'parent_qname': str(from_concept.qname) if concept == to_concept else None,
                            'preferred_label': rel['preferred_label']
                        }
                        concepts.append(concept_info)
                        logger.debug(f"Added concept: {concept_info}")
            
            # Also add any standalone concepts from locators that might not be in relationships
            for label, concept in concepts_by_label.items():
                concept_qname = str(concept.qname)
                if concept_qname not in [c['qname'] for c in concepts]:
                    label = concept.get_label() if hasattr(concept, 'get_label') else 'N/A'
                    logger.debug(f"Standalone Concept: {concept_qname}, Label: {label}")  # Debugging output
                    concept_info = {
                        'name': concept.name,
                        'qname': concept_qname,
                        'label': label,  # Ensure label is fetched
                        'order': None,
                        'parent_qname': None
                    }
                    concepts.append(concept_info)
                    if 'SalesRevenueAutomotive' in concept_qname:
                        logger.info(f"Added standalone SalesRevenueAutomotive concept: {concept_info}")
        
        logger.info(f"Found {len(concepts)} concepts in network")
        
        # Debug output for SalesRevenueAutomotive
        sales_rev_auto = [c for c in concepts if 'SalesRevenueAutomotive' in c['qname']]
        if sales_rev_auto:
            logger.info(f"SalesRevenueAutomotive concepts in final list: {sales_rev_auto}")
        
        return concepts
        
    except Exception as e:
        logger.error(f"Error processing network: {str(e)}")
        logger.debug("Exception details:", exc_info=True)
        return []

def process_children(reporter, network, parent, concepts, grandparent_qname):
    """
    Recursively process children of a concept
    """
    for child, rel in network.get_children(parent):
        # Get the order and preferred label from the relationship
        order = rel.order if hasattr(rel, 'order') else None
        preferred_label = rel.preferred_label if hasattr(rel, 'preferred_label') else None
        
        # Get the appropriate label based on preferred label role
        if preferred_label:
            label = reporter.get_label(child.qname, preferred_label)
        else:
            label = reporter.get_label(child.qname)
            
        child_dict = {
            "name": child.name,
            "qname": child.qname,
            "label": label,
            "order": order,
            "parent_qname": parent.qname,
            "grandparent_qname": grandparent_qname
        }
        concepts.append(child_dict)
        
        # Continue recursion
        process_children(reporter, network, child, concepts, parent.qname)

#load_and_parse_xbrl_to_concept_df

def concept_to_df(instance_file, taxonomy_folder, concept_df_output_file = None, meta = {}, force_recreate = False):
    """
    Modified to ensure proper linkbase loading
    """
    try:
        meta_str = ""
        if meta:
            meta_str = "; ".join([f"{k}={v}" for k,v in meta.items()])
            logger.info(f"Starting to parse for observation: {meta_str}")
        if concept_df_output_file:
            #if os.path.exists(concept_df_output_file) or os.path.exists(concept_df_output_file.replace(".csv", ".p.gz")):
            if os.path.exists(concept_df_output_file.replace(".csv", ".p.gz")):
                logger.info(f"Concepts already parsed, skipping {concept_df_output_file}")
                if not force_recreate:
                    return True
        
        
        # Find required files
        entry_point = None
        presentation_file = None
        for root, dirs, files in os.walk(taxonomy_folder):
            for file in files:
                if file.endswith('.xsd'):
                    entry_point = os.path.join(root, file)
                elif file.endswith('_pre.xml'):
                    presentation_file = os.path.join(root, file)    

        if not entry_point or not presentation_file:
            logger.error(f"Required files not found in {taxonomy_folder}")
            return None

        logger.info(f"\nLoading files:")
        logger.info(f"Entry point: {entry_point}")
        logger.info(f"Presentation: {presentation_file}")

        # Create a new pool with explicit linkbase loading
        data_pool = pool.Pool(cache_folder="../data/xbrl_cache", max_error=1024)

        # Load taxonomy with explicit presentation linkbase
        tax = data_pool.add_taxonomy(
            entry_points=[entry_point],
            linkbase_files=[presentation_file],
            esef_filing_root=taxonomy_folder
        )
        
        # Ensure linkbases are compiled
        if hasattr(tax, 'compile_linkbases'):
            logger.info("Compiling linkbases...")
            tax.compile_linkbases()
            
        # After loading the taxonomy
        logger.info("Loaded concepts:")
        for concept, qname in tax.concepts.items():
            if "SalesRevenueAutomotive" in str(qname) or "RevenueFromContractWithCustomerExcludingAssessedTax" in str(qname):
                logger.info(f"Concept {concept} QName: {qname}")
            
    except Exception as e:
        tb_output = io.StringIO()
        traceback.print_exc(limit=10, file=tb_output)
        logger.error(f"Error loading taxonomy: {e}\n{tb_output.getvalue()}\n{meta_str}")
        tb_output.close()
        return None
    
    # Create taxonomy reporter
    try:    
        reporter = tax_reporter.TaxonomyReporter(tax)
    except Exception as e:
        tb_lines = traceback.format_exc(limit=10)
        logger.error(f"Error loading taxonomy: {e}\n{tb_lines}")                
        return None
    
    logger.info("\nTaxonomy statistics:")
    logger.info(f"Schemas: {len(tax.schemas)}")
    logger.info(f"Linkbases: {len(tax.linkbases)}")
    logger.info(f"Concepts: {len(tax.concepts)}")
    
    # Get presentation networks
    try:    
        networks = get_presentation_networks(tax)
        logger.info(f"\nFound {len(networks)} presentation networks")
    except Exception as e:
        tb_lines = traceback.format_exc(limit=10)
        logger.error(f"Error loading taxonomy: {e}\n{tb_lines}\n{meta_str}")        
        return None
    
    # Store concepts by statement
    

    try:
        concepts_by_statement = {}
        for network in networks:
            statement_name = network.role.split('/')[-1]
            concepts = get_network_details(reporter, network)
            #pd.DataFrame(concepts[0]["children"][0]["children"][0]["children"])
            #pd.DataFrame(concepts[0]["children"][0]["children"][0]["children"])
            if concepts:  # Only add if we found concepts
                concepts_by_statement[statement_name] = concepts
        concept_tree_list = []
        for statement, concepts in concepts_by_statement.items():
            statement_concept = concepts[0]
            this_statement_list = []
            for concept in concepts:
                this_concept_generator = yield_concept_tree(concept) 
                # Collect all levels of concepts
                for this_concept_dict in this_concept_generator:
                    this_concept_dict['statement_label'] = statement_concept["label"]
                    this_concept_dict['statement_name'] = statement_concept["name"]
                    this_statement_list.append(this_concept_dict)
            #this_statement_list = list(set(this_statement_list))         
            concept_tree_list.append(this_statement_list)
        concept_tree_list = list(chain.from_iterable(concept_tree_list))
        df = pd.DataFrame.from_records(concept_tree_list)
        df = df.drop_duplicates(subset=["concept_name"]).reset_index(drop=True)
        if not df.empty:
            df["concept_is_extended"] = df["concept_name"].apply(lambda x: not "ifrs-full" in x)

        # Add required columns if they don't exist
        if 'fact_id' in df.columns:
            # Create numeric fact_id column if needed
            df['fact_id_num'] = pd.to_numeric(df['fact_id'].str.replace('F_', ''), errors='coerce')
        else:
            logger.warning("No fact_id column found in DataFrame")
            # Add a default fact_id column if needed
            df['fact_id'] = [f"F_{i:06d}" for i in range(len(df))]
            df['fact_id_num'] = range(len(df))

        # Sort the DataFrame
        sort_columns = ['fact_id_num'] if 'fact_id_num' in df.columns else ['qname']
        df.sort_values(by=sort_columns, inplace=True)

        # Save to files if output path provided
        if concept_df_output_file:
            df.to_csv(concept_df_output_file, index=False, sep="|")
            df.to_pickle(concept_df_output_file.replace(".csv", ".p.gz"), compression="gzip")

        # Debug output
        logger.info(f"Final DataFrame shape: {df.shape}")
        logger.info(f"Final DataFrame columns: {df.columns}")
        if not df.empty:
            logger.info(f"Sample rows:\n{df.head()}")
        else:
            logger.warning("DataFrame is empty - no concepts were processed successfully")

        return df
        
    except Exception as e:
        tb_lines = traceback.format_exc(limit=10)
        logger.error(f"Error processing concepts: {e}\n{tb_lines}")
        return pd.DataFrame()  # Return empty DataFrame instead of None

def instance_to_df(xid, this_tax):
    # Initialize a list to store dictionaries of fact details
    facts_data = []
    # Get the concept associated with this fact
    for key, fact in xid.xbrl.facts.items():
        # Get the concept associated with this fact
        concept = this_tax.concepts_by_qname.get(fact.qname)
        
        if concept:
            fact_dict = {
                'concept_name': concept.qname,
                'value': fact.value[:100] if "text" in concept.name.lower() else fact.value,
                'unit_ref': fact.unit_ref,
                'decimals': fact.decimals,
                'precision': fact.precision
            }
            
            ref_context = xid.xbrl.contexts.get(fact.context_ref)
            if ref_context:
                # Add period information
                fact_dict['period'] = ref_context.get_period_string()                
                #fact_dict['period_instant'] = ref_context.period_instant
                fact_dict['period_start'] = ref_context.period_start
                #fact_dict['period_end'] = ref_context.period_end
                # # Add entity information
                # fact_dict['entity_scheme'] = ref_context.entity_scheme
                # fact_dict['entity_identifier'] = ref_context.entity_identifier
                # Add segment information
                if ref_context.segment:
                    segment_info = {}
                    for dimension, member in ref_context.segment.items():
                        segment_info[dimension] = member.text if hasattr(member, 'text') else str(member)
                    fact_dict['segment'] = segment_info
                else:
                    fact_dict['segment'] = None
                    
                # Add scenario information
                if ref_context.scenario:
                    scenario_info = {}
                    for dimension, member in ref_context.scenario.items():
                        scenario_info[dimension] = member.text if hasattr(member, 'text') else str(member)
                    fact_dict['scenario'] = scenario_info
                else:
                    fact_dict['scenario'] = None
            
            facts_data.append(fact_dict)
    # Create DataFrame from the collected data
    df_facts = pd.DataFrame(facts_data)
    # Optional: Clean up the DataFrame
    # Remove rows where all values are None or NaN
    #df_facts = df_facts.dropna(how='all')
    return df_facts


def clean_doc(text):
    if type(text) == dict:
        text =  list(text.values())[0]
    text = re.sub(r'^<XBRL>', '', text)
    text = re.sub(r'</XBRL>$', '', text)
    text = re.sub(r"\n", '', text)
    return text

def filing_to_xbrl(url, egl = EG_LOCAL('/text/edgar')):
    """
    url: str
    """
    filing = Filing(url, egl = egl)
    memfs = fs.open_fs('mem://')
    entry_points = []
    
    for key, filename in filing.xbrl_files.items():
        logger.info(f"{key}, {filing.documents[filename].type}, {filename}")
        content = filing.documents[filename].doc_text.data
        content = clean_doc(content)
        with  memfs.open(filename, 'w') as f:
            f.write(content)
        logger.info(f"Successfully cached {filename} to memory, length={len(content)}")
        entry_points.append(f"mem://{filename}")

    memfs.listdir("/")

    entry_points

    data_pool = Pool(max_error=2, esef_filing_root="mem://", memfs=memfs); #self = data_pool


    this_tax = Taxonomy(entry_points=entry_points,
                            container_pool = data_pool, 
                            esef_filing_root="mem://",
                            #in_memory_content=in_memory_content,
                            memfs=memfs)  #

    data_pool.current_taxonomy = this_tax

    if filing.xbrl_files.get("xml"):
        xml_filename = filing.xbrl_files.get("xml")
        instance_str = filing.documents[xml_filename].doc_text.data
        instance_str = clean_doc(instance_str)
        instance_byte = instance_str.encode('utf-8')
        instance_io = BytesIO(instance_byte)
        instance_tree = lxml_etree.parse(instance_io)
        root = instance_tree.getroot()
        data_pool.cache_from_string(location=xml_filename, content=instance_str, memfs=memfs)
        xid = Instance(container_pool=data_pool, root=root, memfs=memfs)


if __name__ == "__main__" and False: # ESEF Example 1
    #from parse_concepts import *
    location_path = os.path.expanduser("~/Dropbox/data/proj/bmcg/bundesanzeiger/public/213034/2021/grammer_Jahres-_2022-05-02_esef_xmls/")
    instance_file = "KALABE.xhtml.html"  # Relative to location_path

    # Full path to instance file
    full_instance_path = os.path.join(location_path, instance_file)
    taxonomy_folder = location_path
    #load_and_parse_xbrl(instance_file, taxonomy_folder)
    #concepts = load_and_parse_xbrl(instance_file, location_path)

    data_pool = pool.Pool(cache_folder="../data/xbrl_cache")
    
    # Find required files
    entry_point = None
    presentation_file = None
    
    for file in os.listdir(taxonomy_folder):
        if file.endswith('.xsd'):
            entry_point = os.path.join(taxonomy_folder, file)
        elif file.endswith('_pre.xml'):
            presentation_file = os.path.join(taxonomy_folder, file)
    
    if not entry_point or not presentation_file:
        raise Exception("Required files not found")

    logger.info(f"\nLoading files:")
    logger.info(f"Entry point: {entry_point}")
    logger.info(f"Presentation: {presentation_file}")

    # Load taxonomy
    taxonomy = data_pool.add_taxonomy([entry_point, presentation_file], esef_filing_root=taxonomy_folder)
    
    
    logger.info("\nTaxonomy statistics:")
    logger.info(f"Schemas: {len(taxonomy.schemas)}")
    logger.info(f"Linkbases: {len(taxonomy.linkbases)}")
    logger.info(f"Concepts: {len(taxonomy.concepts)}")
        


if __name__ == "__main__" and False: # ESEF Example2
    #from parse_concepts import *
    # Specify your ESEF files and folders
    location_path = os.path.expanduser("~/Dropbox/data/proj/bmcg/bundesanzeiger/public/100737/2020/volkswagen_Konzernabschluss_2021-06-08_esef_xmls")
    instance_file = "reports/volkswagenag.xhtml.html.gzip"  # Relative to location_path
    instance_gzip_file = "volkswagenag.xhtml.html.gzip"
    
    # Full path to instance file
    full_instance_path = os.path.join(location_path, instance_file)
    
    # Prepare files
    full_instance_zip_path = os.path.join(location_path, instance_gzip_file)
    instance_file = prepare_files(full_instance_zip_path, location_path)
    
    # Parse the XBRL and group concepts
    instance_file = full_instance_path
    taxonomy_folder = location_path
    #load_and_parse_xbrl(instance_file, taxonomy_folder)
    #concepts = load_and_parse_xbrl(instance_file, location_path)

    data_pool = pool.Pool(cache_folder="../data/xbrl_cache")
    
    # Find required files
    entry_point = None
    presentation_file = None
    
    for file in os.listdir(taxonomy_folder):
        if file.endswith('.xsd'):
            entry_point = os.path.join(taxonomy_folder, file)
        elif file.endswith('_pre.xml'):
            presentation_file = os.path.join(taxonomy_folder, file)
    
    if not entry_point or not presentation_file:
        raise Exception("Required files not found")

    logger.info(f"\nLoading files:")
    logger.info(f"Entry point: {entry_point}")
    logger.info(f"Presentation: {presentation_file}")

    # Load taxonomy
    taxonomy = data_pool.add_taxonomy([entry_point, presentation_file], esef_filing_root=taxonomy_folder)
    
    # Create taxonomy reporter
    reporter = tax_reporter.TaxonomyReporter(taxonomy)
    
    logger.info("\nTaxonomy statistics:")
    logger.info(f"Schemas: {len(taxonomy.schemas)}")
    logger.info(f"Linkbases: {len(taxonomy.linkbases)}")
    logger.info(f"Concepts: {len(taxonomy.concepts)}")
    
    # Get presentation networks
    networks = get_presentation_networks(taxonomy)
    logger.info(f"\nFound {len(networks)} presentation networks")

    # Get presentation networks directly from taxonomy
    networks = []
    for key, base_set in taxonomy.base_sets.items():
        if 'presentation' in str(key).lower():
            networks.append(base_set)
    
    logger.info(f"\nFound {len(networks)} presentation networks")
    
    # Store concepts by statement
    concepts_by_statement = {}
    
    for network in networks:
        statement_name = network.role.split('/')[-1]
        concepts = get_network_details(reporter, network)
        if concepts:  # Only add if we found concepts
            concepts_by_statement[statement_name] = concepts
            


    # Print the results
    #print_concepts_by_statement(concepts_by_statement)

    # print("\n\nget_child_concepts")
    # for statement, concepts in concepts_by_statement.items():
    #     print(f"\n=== {statement} ===")
    #     print("-" * 80)
    #     for concept in concepts:
    #         get_child_concepts(reporter, network, concept, taxonomy, visited=None)

    logger.info("\n\nprint_concept_tree") 
    for statement, concepts in concepts_by_statement.items():
        logger.info(f"\n=== {statement} ===")
        logger.info(concepts)
        logger.info("-" * 80)
        for concept in concepts:
            print_concept_tree(concept, level=0)

    concept_tree_list = []
    for statement, concepts in concepts_by_statement.items():
        statement_concept = concepts[0]
        this_statement_list = []
        for concept in concepts:
            this_concept_generator = yield_concept_tree(concept) 
            # Collect all levels of concepts
            for this_concept_dict in this_concept_generator:
                this_concept_dict['statement_label'] = statement_concept["label"]
                this_concept_dict['statement_name'] = statement_concept["name"]
                this_statement_list.append(this_concept_dict)
        concept_tree_list.append(this_statement_list)

    concept_tree_list = list(chain.from_iterable(concept_tree_list))
    df = pd.DataFrame.from_records(concept_tree_list)
    df["concept_is_extended"] = df["concept_name"].apply(lambda x: not "ifrs-full" in x)
    df.head(30)
    df.to_csv("df.csv", index=False)

    # df1 = get_df_from_concepts_by_statement(concepts_by_statement)
    # df1.head(30)
    # df1.to_csv("concept_tree_df.csv", index=False)

## Since 20250301:
class TaxonomyPresentation:
    """Class to hold taxonomy presentation information"""
    
    def __init__(self, tax, reporter=None):
        self.tax = tax
        self.reporter = reporter
        self.concept_df = None
        self.allowed_segments_by_statement = {}
        self.concept_dict = {}  # Main concept dictionary
        self.statement_concepts = {}  # Concepts from primary statements
        self.disclosure_concepts = {}  # Concepts from disclosures
        self.statement_dimensions = {}  # Track allowed dimensions per statement
        self._process_taxonomy()
        self.populate_concept_df()  # Populate the DataFrame upon initialization
        logger.info(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        logger.info(self.concept_df.statement_name.value_counts())

        so_names = [sn for sn in self.statement_dimensions.keys() if re.search(r"operation|profit|income", sn.lower())]
        self.so_name = so_names[0] if so_names else None
        
        fp_names = [sn for sn in self.statement_dimensions.keys() if re.search(r"balance.?sheet|financial.?position", sn.lower())]
        self.fp_name = fp_names[0] if fp_names else None
        
        cf_names = [sn for sn in self.statement_dimensions.keys() if re.search(r"cash.?flow", sn.lower())]
        self.cf_name = cf_names[0] if cf_names else None
        
        # # Debug output to check what's in the concept dictionary
        # logger.info(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        # if len(self.concept_dict) == 0:
        #     logger.error("ERROR: No concepts were added to the concept dictionary!")
        # else:
        #     # Log a sample of concepts that were added
        #     sample_concepts = list(self.concept_dict.keys())[:10]
        #     logger.info(f"Sample concepts in dictionary: {sample_concepts}")
        #     logger.info([k for k in self.concept_dict.keys() if "SalesRevenueAutomotive" in k])

    def populate_concept_df(self):
        """Populate the concept DataFrame from concept_dict, statement_concepts, and disclosure_concepts."""
        concept_data = []

        # Add statement concepts
        for qname, info in self.statement_concepts.items():
            concept_data.append({
                'concept_name': info['concept_name'],
                'concept_qname': qname,
                'label': info['label'],
                'is_primary_statement': True,
                'statement_name': info['statement_name'],
                'statement_role': info['statement_role'],
                'order': info.get('order', None),
                'dimensions': self.statement_dimensions.get(info['statement_name'], {}).get('dimensions', []),
            })

        # Add disclosure concepts
        for qname, info in self.disclosure_concepts.items():
            concept_data.append({
                'concept_name': info['concept_name'],
                'concept_qname': qname,
                'label': info['label'],
                'is_primary_statement': False,
                'statement_name': "Unknown",
                'statement_role': None,
                'order': None,
                'dimensions': [],
            })

        # Create DataFrame
        self.concept_df = pd.DataFrame(concept_data)

        # Log the shape of the DataFrame
        logger.info(f"Concept DataFrame populated with {len(self.concept_df)} entries.")

    def __str__(self):
        return self.info()

    def __repr__(self):
        return self.info()

    def info(self):
        info_str = '\n'.join([
            f'TaxonomyPresentation object with {len(self.concept_dict)} concepts',
            f'Taxonomy: {self.tax}',
            f'Reporter: {self.reporter}',
            f'Concept DataFrame: {self.concept_df.shape if self.concept_df is not None else "None"}' + f'{self.concept_df.head(30).to_string()}'
        ])  
        if self.so_name:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nIncome Statement: {self.so_name}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.so_name].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo income statement found'
        if self.fp_name:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nBalance Sheet: {self.fp_name}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.fp_name].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo balance sheet found'
        if self.cf_name:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nCash Flow: {self.cf_name}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.cf_name].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo cash flow statement found'
        return info_str
    
    def _is_primary_statement(self, role_name):
        """Determine if a role represents a primary statement; 
        try DocumentAndEntityInformation"""
        statement_keywords = [r'balance', r'operations', r'income', r'cash flow', r'cashflow', r'equity', r'financial position', r'financialposition', r'statement', r'DocumentAndEntityInformation']
        disclosure_keywords = [r'disclosure', r'notes', r'details', r'schedule', r'policies']
        
        role_lower = role_name.lower()
        return any(re.search(keyword, role_lower, flags=re.IGNORECASE) for keyword in statement_keywords) and \
               not any(re.search(keyword, role_lower, flags=re.IGNORECASE) for keyword in disclosure_keywords)

    def _process_network_dimensions(self, network, statement_name):
        concepts = get_network_details(self.tax, network)
        concept_dict = {concept['qname']: concept for concept in concepts}
        for concept in concepts:
            parent_qname = concept.get('parent_qname')
            if parent_qname:
                parent_concept = concept_dict.get(parent_qname)
                if parent_concept:
                    if 'children' not in parent_concept:
                        parent_concept['children'] = []
                    parent_concept['children'].append(concept)
        root_concepts = [concept for concept in concepts if not concept.get('parent_qname')]
        allowed_dimensions = set()
        allowed_members = {}
        
        def process_table_structure(node_dict, current_dimension=None):
            if not node_dict:
                return
            node_name = node_dict.get('qname', str(node_dict))
            if 'Axis' in node_name:
                dimension = node_name
                allowed_dimensions.add(dimension)
                allowed_members[dimension] = set()
                current_dimension = dimension
                logger.info(f"Found dimension: {dimension}")
            if current_dimension and 'Member' in node_name:
                allowed_members[current_dimension].add(node_name)
                logger.info(f"Added member {node_name} to dimension {current_dimension}")
            for child_dict in node_dict.get('children', []):
                process_table_structure(child_dict, current_dimension)
        
        for root in root_concepts:
            process_table_structure(root)
        
        self.statement_dimensions[statement_name] = {
            'dimensions': allowed_dimensions,
            'members': allowed_members
        }

    def _validate_segment(self, segment_data, statement_name):
        """Validate segment data against statement's allowed dimensions"""
        logger.info(f"\nValidating segment for statement: {statement_name}")
        logger.info(f"Segment data: {segment_data}")
        
        if not segment_data:
            logger.info("No segment data - valid by default")
            return True
        
        statement_dims = self.statement_dimensions.get(statement_name)
        if not statement_dims:
            logger.info(f"No dimension info for statement {statement_name} - rejecting segmented fact")
            return False
        
        logger.info(f"Statement dimensions: {statement_dims}")
        
        # Check if dimensions are allowed
        for dimension, member in segment_data.items():
            logger.info(f"Checking dimension: {dimension} with member: {member}")
            
            if dimension not in statement_dims['dimensions']:
                logger.info(f"Dimension {dimension} not allowed in statement")
                return False
            
            # More lenient member validation - if dimension is allowed, accept any member
            # unless we have specific member restrictions
            if dimension in statement_dims['members'] and statement_dims['members'][dimension]:
                if member not in statement_dims['members'][dimension]:
                    logger.info(f"Member {member} not allowed for dimension {dimension}")
                    return False
                else:
                    logger.info(f"Member {member} is allowed for dimension {dimension}")
            else:
                logger.info(f"No specific member restrictions for dimension {dimension}")
        
        logger.info("Segment validation passed")
        return True

    def _process_taxonomy(self):
        """Process taxonomy to build concept dictionaries"""
        logger.info("Processing taxonomy presentation networks")
        
        networks = get_presentation_networks(self.tax)
        logger.info(f"\nFound {len(networks)} presentation networks")

        if not networks:
            logger.warning("No presentation networks found. Adding all concepts from taxonomy.")
            # Add all concepts as disclosures
            for qname, concept in self.tax.concepts_by_qname.items():
                self.disclosure_concepts[str(qname)] = {
                    "concept_name": concept.name,
                    "concept_qname": str(qname),
                    "label": concept.get_label() if hasattr(concept, 'get_label') else None,
                    "statement_name": "Unknown",
                    "statement_role": None,
                    "is_primary_statement": False
                }
            # Copy to main concept dictionary
            self.concept_dict.update(self.disclosure_concepts)
            return
        
        # Debug: Print network roles
        for network in networks:
            #network = networks[3]
            statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
            is_primary = self._is_primary_statement(statement_name)
            logger.info(f"\nProcessing network: {statement_name} (Primary: {is_primary})")
            logger.info(f"  Network role: {getattr(network, 'role', 'No role')} ({type(network)})")

            if isinstance(network, XLink):
                logger.info("XLink network details:")
                if hasattr(network, 'locators'):
                    logger.info(f"Locators: {list(network.locators.keys())}")
                if hasattr(network, 'arcs_from'):
                    logger.info(f"Arcs from: {list(network.arcs_from.keys())}")
            
            # Process network dimensions
            self._process_network_dimensions(network, statement_name)
            
            concepts = get_network_details(self.tax, network)
            logger.info(f"Found {len(concepts)} concepts in network")
            
            # Debug: Print first few concepts
            for concept in concepts[:5]:
                logger.info(f"Processing concept: {concept.get('qname')} with QName format: {str(concept.get('qname'))}")
            
            # Add concepts to appropriate dictionary
            target_dict = self.statement_concepts if is_primary else self.disclosure_concepts
            for concept in concepts:
                concept_qname = concept['qname']
                # Debug: Print when processing SalesRevenueAutomotive
                if 'SalesRevenueAutomotive' in concept_qname:
                    logger.info(f"\nProcessing SalesRevenueAutomotive in network {statement_name}")
                    logger.info(f"Concept details: {concept}")
                
                concept_info = {
                    "concept_name": concept['name'],
                    "concept_qname": concept_qname,
                    "label": concept['label'],
                    "order": concept.get('order'),
                    "parent_qname": concept.get('parent_qname'),
                    "statement_name": statement_name,
                    "statement_role": network.role if hasattr(network, 'role') else None,
                    "is_primary_statement": is_primary
                }
                
                # Only add to target dict if not already present or if this is a primary statement
                if concept_qname not in target_dict or is_primary:
                    target_dict[concept_qname] = concept_info
                    if 'SalesRevenueAutomotive' in concept_qname:
                        logger.info(f"Added SalesRevenueAutomotive to {'statement' if is_primary else 'disclosure'} concepts")
                
                # Add segments
                if hasattr(concept, 'segments'):
                    if statement_name not in self.allowed_segments_by_statement:
                        self.allowed_segments_by_statement[statement_name] = set()
                    self.allowed_segments_by_statement[statement_name].update(concept.get('segments', []))
        
        # Merge dictionaries with priority to statements
        self.concept_dict.update(self.disclosure_concepts)  # Add disclosures first
        self.concept_dict.update(self.statement_concepts)  # Override with statements
        
        # Debug: Final check for SalesRevenueAutomotive
        for dict_name, concepts_dict in [("statement_concepts", self.statement_concepts), 
                                       ("disclosure_concepts", self.disclosure_concepts),
                                       ("concept_dict", self.concept_dict)]:
            for qname in concepts_dict:
                if 'SalesRevenueAutomotive' in qname:
                    logger.info(f"Found SalesRevenueAutomotive in {dict_name}: {qname}")
        
        logger.info(f"\nProcessed {len(self.statement_concepts)} statement concepts and {len(self.disclosure_concepts)} disclosure concepts")

    def is_valid_concept(self, concept_qname):
        """Check if a concept is in the presentation"""
        # Convert to string if it's not already
        concept_qname_str = str(concept_qname)
        
        # Debug output
        result = concept_qname_str in self.concept_dict
        #logger.debug(f"Checking if concept '{concept_qname_str}' is valid: {result}")
        
        # If not found, check if we need to add a prefix
        if not result and ':' not in concept_qname_str:
            # Try with common prefixes
            for prefix in ['us-gaap:', 'ifrs:', 'dei:']:
                prefixed_qname = f"{prefix}{concept_qname_str}"
                if prefixed_qname in self.concept_dict:
                    #logger.debug(f"  Found with prefix: {prefixed_qname}")
                    return True
        
        # # If still not found, log the first few keys in the dictionary for debugging
        # if not result:
        #     #logger.debug(f"  Concept dictionary has {len(self.concept_dict)} entries")
        #     if len(self.concept_dict) > 0:
        #         sample_keys = list(self.concept_dict.keys())[:5]
        #         #logger.debug(f"  Sample keys in concept_dict: {sample_keys}")
        
        return result
    
    def get_concept_info(self, concept_qname):
        """Get information about a concept"""
        info = self.concept_dict.get(concept_qname)
        if info:
            if info.get('statement_name') is not None:
                logger.debug(f"Retrieved info for concept '{concept_qname}': statement={info.get('statement_name')}")
            else:
                logger.warning(f"Retrieved info for concept '{concept_qname} but no statement name")
        else:
            logger.warning(f"No info found for concept '{concept_qname}'")
        return info
    
    def is_valid_segment(self, concept_qname, segment_data, statement_name=None):
        """Check if a segment is valid for a concept"""
        #logger.debug(f"Checking if segment {segment_data} is valid for concept '{concept_qname}'")
        
        if statement_name:
            # Check only in the specified statement
            allowed_segments = self.allowed_segments_by_statement.get(statement_name, {}).get(concept_qname, [])
            result = segment_data in allowed_segments
            logger.info(f"  In statement '{statement_name}': {result}")
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

def ins_facts(xid, tax, t_pres, periods_dict):
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
        
        # Debug output for SalesRevenueAutomotive
        if 'SalesRevenueAutomotive' in str(fact.qname):
            logger.info(f"\nTSLA: Found SalesRevenueAutomotive fact:")
            logger.info(f"  Fact key: {key}")
            logger.info(f"  Concept qname: {fact.qname}")
            logger.info(f"  Concept found in taxonomy: {concept is not None}")
        
        # Skip if concept not found in taxonomy
        if not concept:
            logger.info(f"TSLA: Fact {key}: Concept {fact.qname} not found in taxonomy")
            continue
        

            
        concept_qname = str(concept.qname)
        
        # Additional debug for SalesRevenueAutomotive
        if 'SalesRevenueAutomotive' in concept_qname:
            logger.info(f"  Checking if concept is valid in presentation")
            logger.info(f"  Is valid concept: {t_pres.is_valid_concept(concept_qname)}")
            logger.info(f"  Concept in statement_concepts: {concept_qname in t_pres.statement_concepts}")
            logger.info(f"  Concept in disclosure_concepts: {concept_qname in t_pres.disclosure_concepts}")
        
        # Check if concept is valid in presentation
        if not t_pres.is_valid_concept(concept_qname):
            invalid_concept_count += 1
            if invalid_concept_count <= 10 or 'SalesRevenueAutomotive' in concept_qname:  # Always log SalesRevenueAutomotive
                logger.info(f"TSLA: Fact {key}: Concept {concept_qname} not in presentation")
            continue
            
        # Check if context is valid
        if fact.context_ref not in valid_context_ids:
            invalid_context_count += 1
            if invalid_context_count <= 10 or 'SalesRevenueAutomotive' in concept_qname:
                logger.debug(f"Fact {key}: Context {fact.context_ref} not in valid contexts")
            continue
            
        # Get context information
        ref_context = xid.xbrl.contexts.get(fact.context_ref)
        this_context_dict = periods_dict[fact.context_ref]
        
        # Extract segment data
        segment_data = {}
        if ref_context and hasattr(ref_context, 'segment') and ref_context.segment:
            for dimension, member in ref_context.segment.items():
                segment_data[str(dimension)] = member.text if hasattr(member, 'text') else str(member)
            if 'SalesRevenueAutomotive' in concept_qname:
                logger.info(f"  Segment data: {segment_data}")
        
        # Get concept info with priority to statements
        concept_info = None
        if concept_qname in t_pres.statement_concepts:
            concept_info = t_pres.statement_concepts[concept_qname]
        elif concept_qname in t_pres.disclosure_concepts:
            concept_info = t_pres.disclosure_concepts[concept_qname]
        
        if not concept_info:
            if 'SalesRevenueAutomotive' in concept_qname:
                logger.info("  No concept info found in either statements or disclosures")
            continue
        
        # Validate segment data against statement structure
        statement_name = concept_info.get('statement_name')
        if 'SalesRevenueAutomotive' in concept_qname:
            logger.info(f"  Statement name: {statement_name}")
        
        is_valid_segment = t_pres._validate_segment(segment_data, statement_name)
        if 'SalesRevenueAutomotive' in concept_qname:
            logger.info(f"  Segment validation result: {is_valid_segment}")
        
        is_primary = concept_info.get('is_primary_statement', False)
        if 'SalesRevenueAutomotive' in concept_qname:
            logger.info(f"  Is primary statement: {is_primary}")
        
        fact_included = is_primary and is_valid_segment
        if 'SalesRevenueAutomotive' in concept_qname:
            logger.info(f"  Fact included: {fact_included}")

        fact_dict = {
            # Basic fact information
            'concept_name': concept.name,
            'concept_qname': concept_qname,
            "unit_ref": fact.unit_ref,
            "decimals": fact.decimals,
            'value': fact.value if "text" not in concept.name.lower() else fact.value[:100],
            "value_mln": float(fact.value) / 1000000 if fact.unit_ref is not None and "USD" in fact.unit_ref and fact.decimals == "-6" else None,
            #"precision": fact.precision,
            'context_ref': fact.context_ref,
            
            # Context information
            'period_string': this_context_dict.get("period_string", None),
            'period_type': this_context_dict.get("period_type", None),
            'period_start': this_context_dict.get("period_start", None),
            'period_end': this_context_dict.get("period_end", None),
            'period_instant': this_context_dict.get("period_instant", None),
            'entity_scheme': this_context_dict.get("entity_scheme", None),
            'entity_identifier': this_context_dict.get("entity_identifier", None),
            
            # Segment information
            'segment': segment_data,
            'segment_data': segment_data,
            'has_dimensions': bool(segment_data),
            'dimension_count': len(segment_data) if segment_data else 0,
            'scenario': this_context_dict.get("scenario", None),
            
            # Statement information from concept_info
            'statement_name': statement_name,
            'statement_role': concept_info.get('statement_role'),
            'primary_statement': concept_info.get('is_primary_statement'),
            'appears_in_statements': 1 if concept_info.get('statement_name') else 0,
            'statement_label': (f"{concept_info.get('statement_name')} "
                              f"({concept_info.get('statement_role')})") if concept_info.get('statement_name') else None,
            'parent_qname': concept_info.get('parent_qname'),
            'label': concept_info.get('label'),
            'order': concept_info.get('order'),
            
            # Inclusion flag based on primary statement status and segment validation
            'fact_included': fact_included
        }


        fact_dict['fact_id'] = key
        fact_dict['fact_id_num'] = int(re.findall(r'\d+', key)[0])  if re.findall(r'\d+', key) else None

        ref_context = xid.xbrl.contexts.get(fact.context_ref)
        if ref_context:
            # Add period information
            fact_dict['period'] = ref_context.get_period_string()                
            #fact_dict['period_instant'] = ref_context.period_instant
            fact_dict['period_start'] = ref_context.period_start
            #fact_dict['period_end'] = ref_context.period_end
            # # Add entity information
            # fact_dict['entity_scheme'] = ref_context.entity_scheme
            # fact_dict['entity_identifier'] = ref_context.entity_identifier
            # Add segment information
            if ref_context.segment:
                segment_info = {}
                for dimension, member in ref_context.segment.items():
                    segment_info[dimension] = member.text if hasattr(member, 'text') else str(member)
                fact_dict['segment'] = segment_info
            else:
                fact_dict['segment'] = None
                
            # Add scenario information
            if ref_context.scenario:
                scenario_info = {}
                for dimension, member in ref_context.scenario.items():
                    scenario_info[dimension] = member.text if hasattr(member, 'text') else str(member)
                fact_dict['scenario'] = scenario_info
            else:
                fact_dict['scenario'] = None


        fact_list.append(fact_dict)        

    # Create DataFrame from collected facts
    
    fact_df = pd.DataFrame(fact_list)

    # Figure out the ID range for statement and disclosure respectively by first finding facts that only belong to disclosures and 
    # using their minimum ID as the border.
    # Use that range to determine whether a fact should not belong to any statement.

    # Sort by order if available
    # if 'order' in fact_df.columns and not fact_df['order'].isna().all():
    #     fact_df = fact_df.sort_values('order', na_position='last')
    
    # # Log summary statistics
    # logger.debug(f"Fact extraction complete:")
    # logger.debug(f"  Total facts processed: {len(xid.xbrl.facts)}")
    # logger.debug(f"  Facts included: {included_count}")
    # logger.debug(f"  Facts excluded: {excluded_count}")
    # logger.debug(f"  Invalid concepts: {invalid_concept_count}")
    # logger.debug(f"  Invalid contexts: {invalid_context_count}")
    # logger.debug(f"  Final DataFrame size: {len(fact_df)} rows")
    
    return fact_df

# Add example usage function at the end of the file
if __name__ == "__main__":
    """Example of how to use the TaxonomyPresentation class with order information"""
    from openesef.edgar.loader import load_xbrl_filing
    
    # Load a filing
    xid, tax = load_xbrl_filing(ticker="TSLA", year=2020)
    # logger.info("\n\n================ FINISHED LOADING XBRL FILING =================\n\n")
    # #lets reload a smaller tax
    # location_xbrl = './examples/tsla_2019_min/tsla-20191231_htm.xml'
    # location_taxonomy = './examples/tsla_2019_min/tsla-20191231.xsd'
    # location_linkbase_cal = './examples/tsla_2019_min/tsla-20191231_cal.xml'
    # location_linkbase_def = './examples/tsla_2019_min/tsla-20191231_def.xml'
    # location_linkbase_lab = './examples/tsla_2019_min/tsla-20191231_lab.xml'
    # location_linkbase_pre = './examples/tsla_2019_min/tsla-20191231_pre.xml'

    # # Initialize pool with cache
    # data_pool = Pool(max_error=10)

    # # Load taxonomy
    # entry_points = [location_linkbase_pre, location_taxonomy]
    # tax = data_pool.add_taxonomy(entry_points, esef_filing_root=os.getcwd()+"./examples/tsla_2019_min/")
    
    
    # Create a reporter
    reporter = tax_reporter.TaxonomyReporter(tax)
    
    # Get reporting contexts
    periods_dict = xid.identify_reporting_contexts()
    
    # Create taxonomy presentation with reporter
    t_pres = TaxonomyPresentation(tax, reporter)
    logger.info("\n\n================ FINISHED CREATING TAXONOMY PRESENTATION =================\n\n")
    logger.info(t_pres)
    #logger.info("lets debug the part first.")
    #exit()
    
    # Find statement of operations
    so_names = [sn for sn in t_pres.allowed_segments_by_statement.keys() if "operations" in sn.lower()]
    so_name = so_names[0] if so_names else None
    if so_name:
        logger.info(f"Name <Statement of Operations>: {so_name}")
    else:
        logger.warning("No statement of operations found")
        logger.info(t_pres.allowed_segments_by_statement.keys())
    
    # Extract facts with order information
    fact_df = ins_facts(xid, tax, t_pres, periods_dict)
    fact_df.sort_values(by='fact_id_num', inplace=True)
    
    only_statement_concepts = [concept for concept in t_pres.statement_concepts if concept not in t_pres.disclosure_concepts]
    only_disclosure_concepts = [concept for concept in t_pres.disclosure_concepts if concept not in t_pres.statement_concepts]
    
    min_statement_id_num = None
    min_disclosure_id_num = None
    if only_statement_concepts:
        only_statement_facts = fact_df[fact_df['concept_qname'].isin(only_statement_concepts)]
        #only_statement_facts.statement_name.value_counts()
        if not only_statement_facts.empty:
            min_statement_id_num = only_statement_facts['fact_id_num'].min()
        else:
            min_statement_id_num = float('inf')  # If no statement facts, set a high number    
    
    
    if only_disclosure_concepts:
        only_disclosure_facts = fact_df[fact_df['concept_qname'].isin(only_disclosure_concepts)]
        #only_disclosure_facts.statement_name.value_counts()
        if min_statement_id_num:
            only_disclosure_facts = only_disclosure_facts[only_disclosure_facts['fact_id_num'] >= min_statement_id_num]
        
        if not only_disclosure_facts.empty:
            min_disclosure_id_num = only_disclosure_facts['fact_id_num'].min()
        else:
            min_disclosure_id_num = float('inf')  # If no disclosure facts, set a high number    
        
        fact_df.loc[fact_df['fact_id_num'] >= min_disclosure_id_num, 'fact_included'] = False    
        fact_df.loc[fact_df['fact_id_num'] <= min_disclosure_id_num, 'fact_included'] = True    

    
    # Check order values
    if 'order' in fact_df.columns:
        logger.info(f"Order values present: {fact_df['order'].count()} out of {len(fact_df)}")
        logger.info(f"Sample order values: {fact_df['order'].dropna().head(10).tolist()}")
    
    fact_df = fact_df.sort_values(by='fact_id_num')
    
    # Get facts for a specific period
    #current_period_end = periods_dict[list(periods_dict.keys())[0]]["period_string"]    
    current_period_string = fact_df.period_string.value_counts().index[0]
    current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)
    
    current_so_facts = current_facts.loc[current_facts.statement_name == t_pres.so_name].reset_index(drop=True)
    current_fp_facts = current_facts.loc[current_facts.statement_name == t_pres.fp_name].reset_index(drop=True)
    current_cf_facts = current_facts.loc[current_facts.statement_name == t_pres.cf_name].reset_index(drop=True)
    
    print(current_so_facts[["fact_id", "label", "concept_name", "value_mln", "value", "fact_included"]])
    # Sort by order within statement
    