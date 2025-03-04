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
    logger.debug("\nAccessing presentation networks...")
    
    if 'base_sets' in taxonomy.__dict__:
        logger.debug(f"Number of base sets: {len(taxonomy.base_sets)}")
        
        presentation_networks = []
        for key, base_set in taxonomy.base_sets.items():
            if 'presentation' in str(key).lower():
                logger.debug(f"\nFound presentation base set: {key}")
                presentation_networks.append(base_set)
        
        return presentation_networks
    else:
        print("No base_sets found in taxonomy")
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



def process_children_alt(relationships, parent, concepts, grandparent_qname):
    """
    Alternative recursive function to process children using relationships list
    """
    # Find children of this parent
    children = [rel.target for rel in relationships if rel.source == parent]
    
    for child in children:
        # Find the relationship for this child
        for rel in relationships:
            if rel.source == parent and rel.target == child:
                order = rel.order if hasattr(rel, 'order') else None
                preferred_label = rel.preferred_label if hasattr(rel, 'preferred_label') else None
                break
        else:
            order = None
            preferred_label = None
        
        # Get label
        if preferred_label and hasattr(child, 'get_label'):
            label = child.get_label(role=preferred_label)
        else:
            label = child.get_label() if hasattr(child, 'get_label') else None
        
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
        process_children_alt(relationships, child, concepts, parent.qname)

def get_network_details(tax, network):
    """
    Extract concept details from a presentation network
    
    Args:
        tax: The taxonomy object
        network: The presentation network
        
    Returns:
        List of concept dictionaries with details
    """
    concepts = []
    logger.debug(f"Extracting details from network: {network.role}")
    
    # Check what methods and attributes are available on the network object
    logger.debug(f"Network object type: {type(network)}")
    logger.debug(f"Network object dir: {dir(network)}")
    
    # # Try different approaches to get children
    # if hasattr(network, 'get_children'):
    #     # Original approach
    #     for concept in network.roots:
    #         # Process concept...
    if hasattr(network, 'relationships'):
        # Alternative approach if network has relationships attribute
        logger.debug("Using relationships attribute to process network")
        
        # Get all relationships in the network
        relationships = network.relationships
        
        # Find root concepts (those that don't appear as targets)
        all_sources = set()
        all_targets = set()
        
        for rel in relationships:
            all_sources.add(rel.source)
            all_targets.add(rel.target)
        
        root_concepts = all_sources - all_targets
        
        # Process each root concept
        for concept in root_concepts:
            label = concept.get_label() if hasattr(concept, 'get_label') else None
            concept_dict = {
                "name": concept.name,
                "qname": concept.qname,
                "label": label,
                "order": 0
            }
            logger.debug(f"Root concept: {concept.qname}, Label: {label}, Order: 0")
            concepts.append(concept_dict)
            
            # Find children of this concept
            children = [rel.target for rel in relationships if rel.source == concept]
            
            for child in children:
                # Find the relationship for this child
                for rel in relationships:
                    if rel.source == concept and rel.target == child:
                        order = rel.order if hasattr(rel, 'order') else None
                        preferred_label = rel.preferred_label if hasattr(rel, 'preferred_label') else None
                        break
                else:
                    order = None
                    preferred_label = None
                
                # Get label
                if preferred_label and hasattr(child, 'get_label'):
                    label = child.get_label(role=preferred_label)
                else:
                    label = child.get_label() if hasattr(child, 'get_label') else None
                
                logger.debug(f"Child concept: {child.qname}, Label: {label}, Order: {order}, Parent: {concept.qname}")
                
                child_dict = {
                    "name": child.name,
                    "qname": child.qname,
                    "label": label,
                    "order": order,
                    "parent_qname": concept.qname
                }
                concepts.append(child_dict)
                
                # Process grandchildren recursively
                process_children_alt(relationships, child, concepts, concept.qname)
    else:
        logger.error("Cannot process network: no method to get children")
    
    return concepts

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
    instance_file: str
    taxonomy_folder: str
    concept_df_output_file: str
    meta: dict, a dictionary of metadata for the instance file, such as ISIN company name, filing date, etc

    instance_file = "/Users/mbp16/Dropbox/data/proj/bmcg/bundesanzeiger/public/352123/2023/marley_spoon_2024-05-10_esef_xmls/222100A4X237BRODWF67-2023-12-31-en/marleyspoongroup/reports/222100A4X237BRODWF67-2023-12-31-en.xhtml"
    taxonomy_folder = "/Users/mbp16/Dropbox/data/proj/bmcg/bundesanzeiger/public/352123/2023/marley_spoon_2024-05-10_esef_xmls/222100A4X237BRODWF67-2023-12-31-en/marleyspoongroup/"    
    concept_df_output_file = "/Users/mbp16/Dropbox/data/proj/bmcg/bundesanzeiger/public/352123/2023/marley_spoon_2024-05-10_esef_xmls/"
  
    """
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

    # for file in os.listdir(taxonomy_folder):
    #     if file.endswith('.xsd'):
    #         entry_point = os.path.join(taxonomy_folder, file)
    #     elif file.endswith('_pre.xml'):
    #         presentation_file = os.path.join(taxonomy_folder, file)
    
    if not entry_point or not presentation_file:
        #raise Exception("Required files not found")
        return None
    logger.info(f"\nLoading files:")
    logger.info(f"Entry point: {entry_point}")
    logger.info(f"Presentation: {presentation_file}")

    data_pool = pool.Pool(cache_folder="../data/xbrl_cache", max_error=1024); #self = data_pool

    # Load taxonomy
    try:
        tax = data_pool.add_taxonomy(entry_points = [entry_point, presentation_file], esef_filing_root=taxonomy_folder)
    except Exception as e:
        #logger.error(f"Error loading taxonomy: {e}", exc_info=True)
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
            #pd.DataFrame(concepts[0]["children"][0]["children"][0]["children"][0]["children"])
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

        if concept_df_output_file:
            df.to_csv(concept_df_output_file, index=False, sep="|")  
            df.to_pickle(concept_df_output_file.replace(".csv", ".p.gz"), compression="gzip")

        return True
    except Exception as e:
        tb_lines = traceback.format_exc(limit=10)
        logger.error(f"Error loading taxonomy: {e}\n{tb_lines}\n{meta_str}")                
        return None

    # for network in networks:
    #     network_id = getattr(network, 'role', None)
    #     if network_id is None:
    #         network_id = str(network)
    #     statement_name = network_id.split('/')[-1]
        
    #     # Get all concepts in the network
    #     concepts = get_network_concepts(reporter, network)
    #     concepts_by_statement[statement_name] = concepts
    
    # get_child_concepts(reporter, network, concept, taxonomy, visited=None)

    return concepts_by_statement

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
        logger.debug(f"Initializing TaxonomyPresentation with taxonomy containing {len(tax.concepts)} concepts")
        self.tax = tax  # Store the taxonomy object
        self.concept_df = None
        self.allowed_segments_by_statement = {}
        self.concept_dict = {}  # Indexed by concept_qname for faster lookups
        self._process_taxonomy()
        
        # Debug output to check what's in the concept dictionary
        logger.debug(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        if len(self.concept_dict) == 0:
            logger.error("ERROR: No concepts were added to the concept dictionary!")
        else:
            # Log a sample of concepts that were added
            sample_concepts = list(self.concept_dict.keys())[:10]
            logger.debug(f"Sample concepts in dictionary: {sample_concepts}")
    
    def _process_taxonomy(self):
        """Extract presentation networks from taxonomy"""
        logger.debug("Processing taxonomy presentation networks")
        
        # Get presentation networks
        networks = get_presentation_networks(self.tax)
        logger.debug(f"Found {len(networks)} presentation networks")
        
        # If no networks found, try to get all concepts from taxonomy
        if not networks:
            logger.warning("No presentation networks found. Adding all concepts from taxonomy.")
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
        
        # Process each network
        for network in networks:
            statement_name = network.role.split('/')[-1]
            logger.debug("-"*80)
            logger.debug(f"Processing network: {statement_name}")
            
            concepts = get_network_details(self.tax, network)
            if not concepts:
                logger.debug(f"No concepts found for network: {statement_name}")
                continue
                
            concepts_by_statement[statement_name] = concepts
            allowed_segments_by_concept = {}
            allowed_segments_by_statement[statement_name] = allowed_segments_by_concept
            
            # Process each concept in the network
            concept_count = 0
            new_concept_count = 0
            
            # First pass: collect all parent-child relationships
            parent_child_map = {}  # Maps parent concepts to their children
            axis_member_map = {}   # Maps axes to their members
            
            for concept in concepts:
                this_concept_generator = yield_concept_tree(concept)
                
                for concept_dict in this_concept_generator:
                    concept_count += 1
                    concept_qname = str(concept_dict['concept_qname'])
                    parent_qname = concept_dict.get('parent_qname')
                    
                    # Track parent-child relationships
                    if parent_qname:
                        if parent_qname not in parent_child_map:
                            parent_child_map[parent_qname] = set()
                        parent_child_map[parent_qname].add(concept_qname)
                    
                    # Track axis-member relationships
                    if 'Axis' in concept_qname:
                        if concept_qname not in axis_member_map:
                            axis_member_map[concept_qname] = set()
                    elif 'Member' in concept_qname and parent_qname and 'Axis' in parent_qname:
                        axis_member_map[parent_qname].add(concept_qname)
                    
                    # Initialize allowed segments for this concept
                    if concept_qname not in allowed_segments_by_concept:
                        allowed_segments_by_concept[concept_qname] = set()
                        allowed_segments_by_concept[concept_qname].add(frozenset())  # Empty segment for totals
                    
                    # Only log new concepts to reduce noise
                    if concept_qname not in processed_concepts:
                        processed_concepts.add(concept_qname)
                        new_concept_count += 1
                        
                        # Categorize the concept
                        if 'Axis' not in concept_qname and 'Member' not in concept_qname and 'Domain' not in concept_qname:
                            logger.debug(f"Found line item: {concept_qname}")
                        elif 'Axis' in concept_qname:
                            logger.debug(f"Found axis: {concept_qname}")
                        elif 'Member' in concept_qname:
                            logger.debug(f"Found member: {concept_qname}")
            
            # Second pass: build allowed segments
            for concept_qname in allowed_segments_by_concept.keys():
                # Skip axes, members, and domains for segment building
                if any(x in concept_qname for x in ['Axis', 'Member', 'Domain']):
                    continue
                
                # For each axis in the network
                for axis, members in axis_member_map.items():
                    for member in members:
                        # Associate this member with the concept under the current axis
                        allowed_segments_by_concept[concept_qname].add(
                            frozenset({axis: member}.items())
                        )
            
            logger.debug(f"Processed {concept_count} concepts in network: {statement_name}")
            logger.debug(f"Found {new_concept_count} new unique concepts in this network")
        
        # Build concept DataFrame
        concept_tree_list = []
        for statement, concepts in concepts_by_statement.items():
            statement_concept = concepts[0]
            this_statement_list = []
            
            # Track processed concepts within this statement to avoid duplication
            statement_processed = set()
            
            for concept in concepts:
                this_concept_generator = yield_concept_tree(concept)
                for this_concept_dict in this_concept_generator:
                    concept_qname = str(this_concept_dict['concept_qname'])
                    
                    # Skip if already processed in this statement
                    if concept_qname in statement_processed:
                        continue
                    statement_processed.add(concept_qname)
                    
                    # Preserve all original fields
                    this_concept_dict['statement_label'] = statement_concept.get("label")
                    this_concept_dict['statement_name'] = statement_concept.get("name")
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
            
            # Log a sample of allowed segments (limit to avoid excessive logging)
            sample_concepts = list(allowed_segments_by_concept.keys())[:5]  # First 5 concepts
            logger.debug(f"Sample of allowed segments for {statement_name} (showing first 5 concepts):")
            for concept in sample_concepts:
                segments = allowed_segments_by_concept[concept]
                logger.debug(f"  {concept}: {[dict(s) for s in segments][:3]}...")  # Show first 3 segments
        
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
        
        # If still not found, log the first few keys in the dictionary for debugging
        if not result:
            logger.debug(f"  Concept dictionary has {len(self.concept_dict)} entries")
            if len(self.concept_dict) > 0:
                sample_keys = list(self.concept_dict.keys())[:5]
                logger.debug(f"  Sample keys in concept_dict: {sample_keys}")
        
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
    
    return fact_df

if __name__ == "__main__": # EDGAR iXBRL example
    from openesef.edgar.loader import load_xbrl_filing
    xid, tax = load_xbrl_filing(ticker="TSLA", year=2020)
    logger.debug("\n\n================ FINISHED LOADING XBRL FILEING =================\n\n")
    reporter = tax_reporter.TaxonomyReporter(tax)
    periods_dict = xid.identify_reporting_contexts()

    tax_presentation = TaxonomyPresentation(tax, reporter)
    so_names = [sn for sn in tax_presentation.allowed_segments_by_statement.keys() if "operations" in sn.lower()]
    so_name = so_names[0] if so_names else None
    logger.debug(f"Name <Statement of Operations>: {so_name}")
    fact_df = ins_facts(xid, tax, tax_presentation, periods_dict)
    #fact_df.to_excel("/tmp/tsla_2020_facts.xlsx")
    #fact_df.order
    #fact_df.label
    #current_period_dict = {k: v for k, v in periods_dict.items() if "2019-09-29/2020-09-26" in v["period_string"]}
    #pd.DataFrame.from_records(current_period_dict)
    
    
    # concept_df = concept_df.drop_duplicates().reset_index(drop=True)
    # concept_df_is = concept_df.loc[concept_df.statement_name == "us-gaap:IncomeStatementAbstract"].reset_index(drop=True)
    # #concept_df.loc[concept_df.statement_name == "us-gaap:IncomeStatementAbstract"]

    # fact_df = fact_df.drop_duplicates(subset=["concept_qname", "context_ref"]).reset_index(drop=True)
    # current_fact_df = fact_df.loc[fact_df.period_string == "2019-01-01/2019-12-31"].reset_index(drop=True)
    # current_fact_df.to_excel("/tmp/tsla_2019.xlsx")
    # #current_fact_df_is = current_fact_df.loc[current_fact_df.concept_qname.isin(concept_df_is.concept_qname)].reset_index(drop=True)
    # #current_fact_df_is.to_excel("/tmp/apple_2020_income_statement.xlsx")
    # #fact_df_is = fact_df.loc[(fact_df.statement_name == "us-gaap:IncomeStatementAbstract") ].reset_index(drop=True)
    # df1 = pd.merge(fact_df, concept_df, left_on="concept_qname", right_on="concept_qname")            
    # df1_is = df1.loc[(df1.statement_name == "us-gaap:IncomeStatementAbstract") & (df1.fact_included == True)].reset_index(drop=True)
    # #df1_is.loc[(df1_is.period_string=="2019-01-01/2019-12-31") & (df1_is.concept_qname=="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")]#.to_dict(orient="records")
    # df1_is.to_excel("/tmp/tsla_2019_income_statement.xlsx")
