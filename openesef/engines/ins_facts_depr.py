"""
moved ins_facts() from tax_pres.py to here because it is not cyphon-safe
"""

from openesef.util.util_mylogger import setup_logger 
from openesef.util.ram_usage import check_memory_usage, safe_numeric_conversion, mem_tops
import logging 
import os
import re
import gc
import pandas as pd
import numpy as np
from openesef.taxonomy.xlink import XLink
from itertools import chain
import traceback
import tracemalloc
from tqdm import tqdm
import warnings
import importlib

# Specifically ignore only SettingWithCopyWarning
#warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)
# cython: language_level=3
# distutils: language = c++

# Disable pandas warnings
import pandas as pd
#pd.options.mode.chained_assignment = None

if __name__=="__main__":
    log_filename= "/tmp/log_main_20250310_p0.log"
    if os.path.exists(log_filename):
        os.remove(log_filename)
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/", full_format=True, formatter_string='%(name)s.%(levelname)s: %(message)s',pid=0)
else:
    logger = logging.getLogger("openesef.engines.ins_facts") 

def ins_facts(xid, tax):
    """Extract facts from instance"""
    if xid is None or tax is None:
        logger.warning("xid or tax is None")
        return None
    if xid.xbrl is None:
        logger.warning("xid.xbrl is None")
        return None
    
    # Lazy import to avoid circular dependency - only import when needed
    tax_pres_module = importlib.import_module('openesef.engines.tax_pres')
    t_pres = tax_pres_module.TaxonomyPresentation(tax)
    
    periods_dict = xid.identify_reporting_contexts()
    logger.info(f"Starting fact extraction with {len(xid.xbrl.facts)} facts and {len(periods_dict)} valid contexts")

    # Create a dictionary to store all statement appearances for each concept
    concept_statement_appearances = {}
    primary_statement_names = list()
    disclosure_names = list()
    
    # Before the fact_list loop, build concept hierarchies for each network
    network_hierarchies = {}
    pres_networks = tax_pres_module.TaxonomyPresentation.get_presentation_networks(tax)
    
    # First pass - record all statement appearances for each concept
    for network in pres_networks:
        statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
        network_hierarchies[statement_name] = tax_pres_module.build_concept_hierarchy(network, tax, t_pres.reporter)
        concepts = tax_pres_module.get_network_details(tax, network, t_pres.reporter)
        
        for concept in concepts:
            concept_qname = concept['qname']
            if concept_qname not in concept_statement_appearances:
                concept_statement_appearances[concept_qname] = []
            
            # Get the concept object to access its labels
            concept_obj = tax.concepts_by_qname.get(concept_qname)
            preferred_label = None
            if concept_obj and hasattr(concept_obj, 'labels'):
                terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                if terse_role in concept_obj.labels:
                    preferred_label = concept_obj.get_label(role=terse_role, lang='en-US')
                if not preferred_label or preferred_label == 'N/A':
                    preferred_label = concept_obj.get_label(lang='en-US')
            
            statement_info = {
                'statement_name': statement_name,
                'statement_role': network.role if hasattr(network, 'role') else None,
                'is_primary_statement': t_pres._is_primary_statement(statement_name),
                'order': concept.get('order'),
                'parent_qname': concept.get('parent_qname'),
                'label': preferred_label if preferred_label else concept.get('label')
            }
            if statement_info['is_primary_statement'] and not statement_info['statement_name'] in primary_statement_names:
                primary_statement_names.append(statement_name)
            else:
                disclosure_names.append(statement_name)
            concept_statement_appearances[concept_qname].append(statement_info)
    
    logger.info("Finished checking network with concepts")
    fact_list = []
    fact_list_disclosure = []
    
    # Process primary statements first
    for primary_statement_name in primary_statement_names:
        logger.debug(f"Processing facts for primary statement: {primary_statement_name}")
        added_concepts_for_this_statement = {}
        for key, fact in xid.xbrl.facts.items():
            concept = tax.concepts_by_qname.get(fact.qname)
            if not concept:
                continue
            
            concept_qname = str(concept.qname)
            statement_appearances = concept_statement_appearances.get(concept_qname, [])
            
            # Find the statement_info that matches the current primary_statement_name
            statement_info = None
            for app in statement_appearances:
                if app['statement_name'] == primary_statement_name and app['is_primary_statement']:
                    statement_info = app
                    #included_facts[key] = True
                    break
            
            if not statement_info:
                continue
            
            try:
                # Get the preferred label for display
                preferred_label = None
                if hasattr(concept, 'labels'):
                    # Try terse label first
                    terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                    if terse_role in concept.labels:
                        preferred_label = concept.get_label(role=terse_role, lang='en-US')
                    # If no terse label, try standard label
                    if not preferred_label or preferred_label == 'N/A':
                        preferred_label = concept.get_label(lang='en-US')
                
                # Safely convert numeric values
                if fact.value is not None:
                    if fact.unit_ref is not None and "usd" in fact.unit_ref.lower() and fact.decimals == "-6":
                        raw_value = safe_numeric_conversion(fact.value)
                        value_mln = raw_value / 1000000 if raw_value is not None else None
                    else:
                        value_mln = None
                        
                    # For text storage, limit length and handle numeric values
                    if "text" in concept.name.lower():
                        stored_value = fact.value[:100]  # Truncate long text
                    else:
                        stored_value = safe_numeric_conversion(fact.value, default=str(fact.value))
                else:
                    stored_value = None
                    value_mln = None

                # Get segment data from context
                segment_data = {}
                segment_member_label = None
                ref_context = xid.xbrl.contexts.get(fact.context_ref)
                if ref_context and hasattr(ref_context, 'segment') and ref_context.segment:
                    #logger.debug(f"There are {len(ref_context.segment)} segments in the context")
                    items = list(ref_context.segment.items()) 
                    if items:
                        dimension, member = items[0]
                        member_value = member.text if hasattr(member, 'text') else str(member)
                        segment_data[str(dimension)] = member_value
                        
                        # Get the label for the segment member
                        member_qname = str(member_value)
                        member_concept = tax.concepts_by_qname.get(member_qname)
                        if member_concept and hasattr(member_concept, 'labels'):
                            terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                            if terse_role in member_concept.labels:
                                segment_member_label = member_concept.get_label(role=terse_role, lang='en-US')
                            if not segment_member_label or segment_member_label == 'N/A':
                                segment_member_label = member_concept.get_label(lang='en-US')
                
                fact_dict = {
                    # Basic fact information
                    'fact_index': fact.fact_index,
                    'concept_name': concept.name,
                    'concept_qname': concept_qname,
                    "unit_ref": fact.unit_ref,
                    "decimals": fact.decimals,
                    'value': stored_value,
                    'value_mln': value_mln,
                    'context_ref': fact.context_ref,
                    
                    # Context information from periods_dict
                    'period_string': periods_dict.get(fact.context_ref, {}).get("period_string"),
                    'period_type': concept.period_type if hasattr(concept, 'period_type') else None,
                    'period_start': periods_dict.get(fact.context_ref, {}).get("period_start"),
                    'period_end': periods_dict.get(fact.context_ref, {}).get("period_end"),
                    'period_instant': periods_dict.get(fact.context_ref, {}).get("period_instant"),
                    'entity_scheme': periods_dict.get(fact.context_ref, {}).get("entity_scheme"),
                    'entity_identifier': periods_dict.get(fact.context_ref, {}).get("entity_identifier"),
                    
                    # Segment information as separate columns
                    'segment_axis': None,
                    'segment_axis_member': None,
                    'segment_dimension': None,
                    'segment_dimension_member': None,
                    'has_dimensions': False,
                    'dimension_count': 0,
                    
                    # Statement information from the selected appearance
                    'statement_name': statement_info['statement_name'],
                    'statement_role': statement_info['statement_role'],
                    'primary_statement': statement_info['is_primary_statement'],
                    'appears_in_statements': len(statement_appearances),
                    'statement_appearances': [app['statement_name'] for app in statement_appearances],
                    'statement_label': (f"{statement_info['statement_name']} "
                                    f"({statement_info['statement_role']})") if statement_info['statement_name'] else None,
                    'parent_qname': statement_info['parent_qname'],
                    'label': (f"{segment_member_label}" if segment_member_label else 
                             preferred_label if preferred_label else 
                             statement_info['label']),
                    'order': statement_info['order'],
                    'is_disclosure': False,
                    # Set fact_included based on primary statement status and segment validation
                    'fact_included': statement_info['is_primary_statement'] and t_pres._validate_segment(segment_data, statement_info['statement_name'])
                }

                # Get additional context information directly from the context object
                ref_context = xid.xbrl.contexts.get(fact.context_ref)
                if ref_context:
                    # Update period information
                    fact_dict['period'] = ref_context.get_period_string()
                    fact_dict['period_type'] = concept.period_type if hasattr(concept, 'period_type') else None
                    fact_dict['period_start'] = ref_context.period_start
                    fact_dict['period_end'] = ref_context.period_end
                    fact_dict['period_instant'] = ref_context.period_instant if hasattr(ref_context, 'period_instant') else None
                    
                    # Update entity information
                    fact_dict['entity_scheme'] = ref_context.entity_scheme if hasattr(ref_context, 'entity_scheme') else None
                    fact_dict['entity_identifier'] = ref_context.entity_identifier if hasattr(ref_context, 'entity_identifier') else None
                    
                    # Update segment information
                    if hasattr(ref_context, 'segment') and ref_context.segment:
                        items = list(ref_context.segment.items())
                        if items:
                            dimension, member = items[0]
                            member_value = member.text if hasattr(member, 'text') else str(member)
                            fact_dict['segment_axis'] = str(dimension)
                            fact_dict['segment_axis_member'] = member_value
                            fact_dict['segment_dimension'] = str(dimension)
                            fact_dict['segment_dimension_member'] = member_value
                    
                    # Update scenario information
                    if hasattr(ref_context, 'scenario') and ref_context.scenario:
                        scenario_info = {}
                        for dimension, member in ref_context.scenario.items():
                            scenario_info[str(dimension)] = member.text if hasattr(member, 'text') else str(member)
                        fact_dict['scenario'] = scenario_info
                    else:
                        fact_dict['scenario'] = None

                # Add concept parents
                statement_name = fact_dict['statement_name']
                concept_qname = fact_dict['concept_qname']
                fact_dict['concept_parents'] = network_hierarchies.get(statement_name, {}).get(concept_qname, [])

                fact_dict['fact_id'] = key

                this_fact_dict = {
                        "value": fact_dict['value'],    
                        #"statement_name": statement_name,
                        #"concept_qname": concept_qname,
                        "segment_axis": segment_data.get("segment_axis"), 
                        "segment_axis_member": segment_data.get("segment_axis_member"),
                        "segment_dimension": segment_data.get("segment_dimension"),
                        "segment_dimension_member": segment_data.get("segment_dimension_member")
                }
                # Create a unique key for this fact that includes all relevant dimensions
                fact_key = (
                    concept_qname,
                    fact_dict['value'],
                    fact_dict.get('segment_axis'),
                    fact_dict.get('segment_axis_member'),
                    fact_dict.get('period_string')
                )
                
                # Only add if we haven't seen this exact fact for this statement
                if statement_name in primary_statement_names and fact_key not in added_concepts_for_this_statement:
                    fact_list.append(fact_dict)
                    added_concepts_for_this_statement[fact_key] = True
                

            except Exception as e:
                logger.error(f"Error processing fact {key}: {str(e)}")
                continue
    logger.info(f"Finished extracting facts for primary statements with {len(fact_list)} facts")
    #mem_tops(top_n=10)            
    #check_memory_usage(threshold_gb=16)
    # Then process disclosures
    
    for key, fact in xid.xbrl.facts.items():
        # if included_facts.get(key, True):
        #     continue
        #for disclosure_name in tqdm(disclosure_names):
        #logger.debug(f"Processing facts for disclosure: {disclosure_name}")    
        #    for key, fact in xid.xbrl.facts.items():
        concept = tax.concepts_by_qname.get(fact.qname)
        if not concept:
            continue

        concept_qname = str(concept.qname)
        statement_appearances = concept_statement_appearances.get(concept_qname, [])
        
        # Find the statement_info that matches the current primary_statement_name
        statement_info = None
        for app in statement_appearances:
            if not app['is_primary_statement']:
                statement_info = app
                break

        if not statement_info:
            continue
        
        # concept_qname = str(concept.qname)
        # statement_appearances = concept_statement_appearances.get(concept_qname, [])
        
        # Find the statement_info that matches the current disclosure_name
        # statement_info = None
        # for app in statement_appearances:
        #     if app['statement_name'] == disclosure_name and not app['is_primary_statement']:
        #         statement_info = app
        #         break
        
        # if not statement_info:
        #     continue

        try:
            # Minimal fact dictionary with only essential information
            fact_dict = {
                'fact_index': fact.fact_index,
                'concept_name': concept.name,
                'concept_qname': concept_qname,
                'value': str(fact.value)[:100] if fact.value is not None else None,  # Truncate long values
                'context_ref': fact.context_ref,
                'statement_name': statement_info['statement_name'],
                'statement_role': statement_info['statement_role'],
                'primary_statement': False,  # These are disclosures
                'fact_id': key,
                'is_disclosure': True
            }
            
            # Add minimal context information if needed
            ref_context = xid.xbrl.contexts.get(fact.context_ref)
            if ref_context:
                fact_dict['period_string'] = periods_dict.get(fact.context_ref, {}).get("period_string")

            
            fact_list_disclosure.append(fact_dict)

        except Exception as e:
            logger.error(f"Error processing fact {key}: {str(e)}")
            continue
        
        except Exception as e:

            logger.error(f"Error processing fact {key}: {str(e)}")
            continue
    logger.info(f"Finished extracting facts for disclosures with {len(fact_list_disclosure)} facts")
    #mem_tops(top_n=30)            
    #check_memory_usage(threshold_gb=16)
    # Create DataFrames from collected facts
    fact_df = pd.DataFrame(fact_list)
    if "statement_name_norm"  in fact_df.columns:
        fact_df.loc[:, 'statement_name_norm'] = fact_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
    else:
        fact_df['statement_name_norm'] = fact_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)

    if "statement_type"  in fact_df.columns:
        fact_df.loc[:, 'statement_type'] = fact_df['statement_name'].map(t_pres.statement_types)
    else:
        fact_df['statement_type'] = fact_df['statement_name'].map(t_pres.statement_types)

    # Convert order to numeric and then to integer safely
    fact_df.loc[:, 'order'] = pd.to_numeric(fact_df['order'], errors='coerce')
    # Fill NaN with a large number to put them at the end
    
    # fact_df.loc[:, 'order'] = np.where(fact_df['order'].isna(), 
    #                            max_order + 100000 if pd.notna(max_order) else 99999,
    #                            fact_df['order'])
    #fact_df.loc[:, 'order'] = fact_df['order'].fillna(max_order + 100000 if pd.notna(max_order) else 99999)                           
    # Convert order to numeric and handle NaN values safely
    fact_df.loc[:, 'order'] = pd.to_numeric(fact_df['order'], errors='coerce')
    max_order = fact_df['order'].max()
    fill_value = max_order + 100000 if pd.notna(max_order) else 99999
    fact_df.loc[:,'order'] = np.where(fact_df['order'].isna(), fill_value, fact_df['order']).astype(int)
    
    
    fact_df = fact_df.sort_values(['statement_type', 'order']).copy()

    fact_df_disclosure = pd.DataFrame(fact_list_disclosure)
    if "statement_name_norm"  in fact_df_disclosure.columns:
        #fact_df_disclosure.loc[:, 'statement_name_norm'] = fact_df_disclosure['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
        raise ValueError("statement_name_norm already exists")
    else:
        fact_df_disclosure['statement_name_norm'] = fact_df_disclosure['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)

    if "statement_type"  in fact_df_disclosure.columns:
        #fact_df_disclosure.loc[:, 'statement_type'] = "Disclosure"
        raise ValueError("statement_type already exists")
    else:
        fact_df_disclosure['statement_type'] = "Disclosure"

    # Ensure numeric columns are properly typed
    numeric_columns = ['value_mln']
    for col in numeric_columns:
        if col in fact_df.columns:
            fact_df[col] = pd.to_numeric(fact_df[col], errors='coerce')
        if col in fact_df_disclosure.columns:
            fact_df_disclosure[col] = pd.to_numeric(fact_df_disclosure[col], errors='coerce')

    # Process calculations if available
    calc_df = tax_pres_module.tax_calc_df(tax)
    if not calc_df.empty:
        # Add statement name normalization to both DataFrames
        # This helps with matching since role_name and statement_name may have slight differences
        if "role_name_norm" not in calc_df.columns:
            calc_df['role_name_norm'] = calc_df['role_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
        else:
            raise ValueError("role_name_norm already exists")
        
        # Group calculation relationships by role and concept
        calc_by_role_parent = calc_df.groupby(['role_name_norm', 'from_qname'])[['to_qname', 'weight']].apply(
            lambda x: dict(zip(x['to_qname'], x['weight']))
        ).to_dict()
        
        calc_by_role_child = calc_df.groupby(['role_name_norm', 'to_qname'])[['from_qname', 'weight']].apply(
            lambda x: dict(zip(x['from_qname'], x['weight']))
        ).to_dict()
        
        # Function to get calculation children for a concept in a specific statement
        def get_calc_children_with_weights(row):
            key = (row['statement_name_norm'], row['concept_qname'])
            return calc_by_role_parent.get(key, {})
        
        # Function to get calculation parents for a concept in a specific statement
        def get_calc_parents_with_weights(row):
            key = (row['statement_name_norm'], row['concept_qname'])
            return calc_by_role_child.get(key, {})
        
        # Add calculation information to the facts DataFrame
        if "is_calc_parent" not in fact_df.columns:
            fact_df['is_calc_parent'] = fact_df.apply(
                lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_parent, 
                axis=1
            )
        else:
            raise ValueError("is_calc_parent already exists")

        if "is_calc_child" not in fact_df.columns:
            fact_df['is_calc_child'] = fact_df.apply(
                lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_child, 
                axis=1
            )
        else:
            raise ValueError("is_calc_child already exists")

        if "calc_children_with_weights" not in fact_df.columns:
            fact_df['calc_children_with_weights'] = fact_df.apply(get_calc_children_with_weights, axis=1)
        else:
            raise ValueError("calc_children_with_weights already exists")

        if "calc_parents_with_weights" not in fact_df.columns:
            fact_df['calc_parents_with_weights'] = fact_df.apply(get_calc_parents_with_weights, axis=1)
        else:
            raise ValueError("calc_parents_with_weights already exists")
        # Extract just the list of children and parents (without weights)
        if "calc_children" not in fact_df.columns:
            fact_df['calc_children'] = fact_df['calc_children_with_weights'].apply(lambda x: list(x.keys()))
        else:
            raise ValueError("calc_children already exists")

        if "calc_parents" not in fact_df.columns:
            fact_df['calc_parents'] = fact_df['calc_parents_with_weights'].apply(lambda x: list(x.keys()))
        else:
            raise ValueError("calc_parents already exists")
    # Update fact_included based on ID ranges for each primary statement
    fact_df = fact_df.sort_values(by='fact_index').copy()
    fact_df_disclosure = fact_df_disclosure.sort_values(by='fact_index').copy()

    if "is_disclosure" not in fact_df.columns:
        fact_df['is_disclosure'] = False
    else:
        fact_df.loc[:, 'is_disclosure'] = False

    if "is_disclosure" not in fact_df_disclosure.columns:
        fact_df_disclosure['is_disclosure'] = True
    else:
        fact_df_disclosure.loc[:, 'is_disclosure'] = True
    # Get concepts that only appear in statements or disclosures
    only_statement_concepts = [concept for concept in t_pres.statement_concepts if concept not in t_pres.disclosure_concepts]
    only_disclosure_concepts = [concept for concept in t_pres.disclosure_concepts if concept not in t_pres.statement_concepts]
    
    # Process each primary statement separately
    for primary_statement_name in primary_statement_names:
        # Get facts for this statement
        statement_facts = fact_df[fact_df['statement_name'] == primary_statement_name].copy()
        
        if statement_facts.empty:
            continue
            
        # Update fact_included based on both statement membership and segment validation
        # Create the mask
        mask = (fact_df['statement_name'] == primary_statement_name)

        # Calculate new values directly on the original DataFrame
        fact_df.loc[mask, 'fact_included'] = fact_df.loc[mask].apply(
            lambda row: (
                row['primary_statement'] and (
                    (pd.isna(row['segment_axis']) and pd.isna(row['segment_dimension'])) or
                    t_pres._validate_segment(
                        {
                            row['segment_axis']: row['segment_axis_member'] if pd.notna(row['segment_axis_member']) else None,
                            row['segment_dimension']: row['segment_dimension_member'] if pd.notna(row['segment_dimension_member']) else None
                        } if pd.notna(row['segment_axis']) or pd.notna(row['segment_dimension']) else {},
                        primary_statement_name
                    )
                )
            ),
            axis=1
        )        
        # Move non-validated dimensional facts to disclosures
        dimensional_mask = mask & (
            (fact_df['segment_axis'].notna() & ~fact_df['fact_included']) |
            (fact_df['segment_dimension'].notna() & ~fact_df['fact_included'])
        )
        #fact_df['statement_type'] = np.where(dimensional_mask, 'Disclosure', fact_df['statement_type'])
        #fact_df['is_disclosure'] = np.where(dimensional_mask, True, fact_df['is_disclosure'])
        #fact_df['fact_included'] = np.where(dimensional_mask, False, fact_df['fact_included'])
        fact_df.loc[dimensional_mask, 'statement_type'] = 'Disclosure'
        fact_df.loc[dimensional_mask, 'is_disclosure'] = True
        fact_df.loc[dimensional_mask, 'fact_included'] = False

    fact_df = pd.concat([fact_df, fact_df_disclosure])
    # Convert to boolean, treating NaN as False
    if not 'fact_included' in fact_df.columns:
        raise ValueError("fact_included not in fact_df")
    else:
        fact_df.loc[:,'fact_included'] = pd.to_numeric(fact_df['fact_included'], errors='coerce').fillna(0).astype(bool)
    #mem_tops(top_n=10)
    #mem_tops(top_n=100)            
    check_memory_usage(threshold_gb=16)

    
    # Update fact_included for this statement's facts


    
    for thisobj in [t_pres, xid, tax, periods_dict, fact_df_disclosure, fact_list_disclosure, fact_list, concept_statement_appearances, network_hierarchies, primary_statement_names, disclosure_names, only_statement_concepts, only_disclosure_concepts]:
        try:
            del thisobj
        except:
            pass
    try:
        gc.collect()
    except:
        pass
    logger.info("Fact extraction completed")
    return fact_df

