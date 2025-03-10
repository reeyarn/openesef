"""


"""

from openesef.util.util_mylogger import setup_logger 
from openesef.util.ram_usage import check_memory_usage, safe_numeric_conversion, mem_tops
from openesef.engines.ins_facts import ins_facts
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

# Specifically ignore only SettingWithCopyWarning
#warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)
# cython: language_level=3
# distutils: language = c++

# Disable pandas warnings
import pandas as pd
#pd.options.mode.chained_assignment = None

if __name__=="__main__":
    log_filename= "/tmp/log_main_20250305_p0.log"
    if os.path.exists(log_filename):
        os.remove(log_filename)
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/", full_format=True, formatter_string='%(name)s.%(levelname)s: %(message)s',pid=0)
else:
    logger = logging.getLogger("openesef.engines.tax_pres") 

## Since 20250301:
class TaxonomyPresentation:
    """
    Main class that processes taxonomy presentation networks and organizes concepts into 
    primary statements and disclosures.
    
    Attributes:
        tax: The taxonomy object being processed
        reporter: TaxonomyReporter instance for label handling
        concept_df: DataFrame containing all concepts
        allowed_segments_by_statement: Dict mapping statements to allowed segments
        concept_dict: Dict containing all concepts
        statement_concepts: Dict mapping statement names to lists of concept details
        disclosure_concepts: Dict mapping disclosure names to lists of concept details
        statement_dimensions: Dict containing allowed dimensions per statement
        so_name: Name of Statement of Operations
        fp_name: Name of Financial Position statement
        cf_name: Name of Cash Flow statement
    
    Methods:
        populate_concept_df(): Creates DataFrame from concept dictionaries
        _is_primary_statement(role_name): Determines if a role represents a primary statement
        _process_network_dimensions(network, statement_name): Processes dimensions in a network
        _validate_segment(segment_data, statement_name): Validates segment data against statement
        _process_taxonomy(): Main method to process taxonomy and build concept dictionaries
        is_valid_concept(concept_qname): Checks if a concept exists in presentation
        get_concept_info(concept_qname): Gets detailed information about a concept
        is_valid_segment(concept_qname, segment_data, statement_name): Validates segment data    
    """
    def __init__(self, tax, reporter=None):
        self.tax = tax
        self.reporter = reporter
        self.concept_df = None
        self.link_df = None
        self.allowed_segments_by_statement = {}
        self.concept_dict = {}  # Main concept dictionary
        self.statement_concepts = {}  # Dict mapping statement names to concept lists
        self.disclosure_concepts = {}  # Dict mapping disclosure names to concept lists
        self.statement_dimensions = {}  # Track allowed dimensions per statement
        self._process_taxonomy() # THE MAIN FUNCTION
        self.statement_types = {}
        self.name_sop = self._get_primary_statement_name(r"operation|profit|income|earning")
        self.name_sfp = self._get_primary_statement_name(r"balance.?sheet|financial.?position")
        self.name_scf = self._get_primary_statement_name(r"cash.?flow|statement.?of.?cash")
        if not all([self.name_sop, self.name_sfp, self.name_scf]):
            logger.warning(f"Not all primary statements found: SOP={self.name_sop}, SFP={self.name_sfp}, SCF={self.name_scf}")
        
        #SOP: Statement of Operations, SFP: Statement of Financial Position, CFS: Statement of Cash Flows
        self.statement_types = {
            name: type_code 
            for name, type_code in {
                self.name_sop: "SOP", 
                self.name_sfp: "SFP", 
                self.name_scf: "CFS"
            }.items() 
            if name is not None
        }
        
        self.populate_concept_df()  # Populate the DataFrame upon initialization
        logger.info(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        logger.info(self.concept_df.statement_name.value_counts())

        
        # # Debug output to check what's in the concept dictionary
        # logger.info(f"TaxonomyPresentation initialized with {len(self.concept_dict)} concepts")
        # if len(self.concept_dict) == 0:
        #     logger.error("ERROR: No concepts were added to the concept dictionary!")
        # else:
        #     # Log a sample of concepts that were added
        #     sample_concepts = list(self.concept_dict.keys())[:10]
        #     logger.info(f"Sample concepts in dictionary: {sample_concepts}")
        #     logger.info([k for k in self.concept_dict.keys() if "SalesRevenueAutomotive" in k])


    def _get_primary_statement_name(self, pattern):
        """Helper method to find primary statement name matching pattern"""
        matching_names = [
            sn for sn in self.statement_dimensions.keys() 
            if (re.search(pattern, sn.lower()) and 
                self._is_primary_statement(sn) and  # Ensure it's a primary statement
                not re.search(r'disclosure|notes|details|schedule|policies|table', sn.lower()))  # Exclude disclosures
        ]
        # Sort by length to prefer shorter, cleaner names
        matching_names.sort(key=len)
        return matching_names[0] if matching_names else None
    def _process_taxonomy(self):
        """Process taxonomy to build concept dictionaries"""
        logger.info("Processing taxonomy presentation networks")
        
        networks = TaxonomyPresentation.get_presentation_networks(self.tax)
        logger.info(f"\nFound {len(networks)} presentation networks")

        if not networks:
            logger.warning("No presentation networks found. Adding all concepts to unknown disclosure.")
            # Add all concepts as disclosures under "Unknown"
            self.disclosure_concepts["Unknown"] = []
            for qname, concept in self.tax.concepts_by_qname.items():
                label = concept.get_label() if hasattr(concept, 'get_label') else None
                concept_info = {
                    "concept_name": concept.name,
                    "concept_qname": str(qname),
                    "label": label,
                    "statement_name": "Unknown",
                    "statement_role": None,
                    "is_primary_statement": False
                }
                self.disclosure_concepts["Unknown"].append(concept_info)
                self.concept_dict[str(qname)] = concept_info
            return
        
        # Process each network
        for network in networks:
            statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
            is_primary = self._is_primary_statement(statement_name)
            if is_primary:
                logger.debug(f"\nProcessing network: {statement_name} (Primary: {is_primary})")
            
            # Process network dimensions
            self._process_network_dimensions(network, statement_name)
            
            # Get concepts using reporter for labels
            concepts = get_network_details(self.tax, network, self.reporter)
            logger.debug(f"Found {len(concepts)} concepts in network")
            
            # Initialize lists for this network if not already present
            target_dict = self.statement_concepts if is_primary else self.disclosure_concepts
            if statement_name not in target_dict:
                target_dict[statement_name] = []
            
            # Add concepts to appropriate network list
            for concept in concepts:
                concept_qname = concept['qname']
                
                # Get segment/dimension information from the statement_dimensions
                segment_info = self.statement_dimensions.get(statement_name, {})
                dimensions = segment_info.get('dimensions', set())
                members = segment_info.get('members', {})
                
                # Create base concept info
                concept_info = {
                    "concept_name": concept['name'],
                    "concept_qname": concept_qname,
                    "label": concept['label'],
                    "order": concept.get('order'),
                    "parent_qname": concept.get('parent_qname'),
                    "statement_name": statement_name,
                    "statement_role": network.role if hasattr(network, 'role') else None,
                    "is_primary_statement": is_primary,
                    # Add segment information
                    "segment_axes": list(dimensions),
                    "segment_members": {str(dim): list(mems) for dim, mems in members.items()},
                    "has_dimensions": len(dimensions) > 0,
                    "dimension_count": len(dimensions)
                }
                
                # For each dimension, create a separate concept entry with segment info
                if dimensions:
                    for dimension in dimensions:
                        dimension_members = members.get(dimension, [])
                        for member in dimension_members:
                            segment_concept_info = concept_info.copy()
                            segment_concept_info.update({
                                "segment_axis": str(dimension),
                                "segment_axis_member": str(member),
                                "segment_dimension": str(dimension),
                                "segment_dimension_member": str(member)
                            })
                            target_dict[statement_name].append(segment_concept_info)
                            # Also maintain in flat concept dictionary
                            key = f"{concept_qname}_{dimension}_{member}"
                            self.concept_dict[key] = segment_concept_info
                else:
                    # Add the concept without segment information
                    concept_info.update({
                        "segment_axis": None,
                        "segment_axis_member": None,
                        "segment_dimension": None,
                        "segment_dimension_member": None
                    })
                    target_dict[statement_name].append(concept_info)
                    self.concept_dict[concept_qname] = concept_info
        
        # Merge dictionaries with priority to statements
        self.concept_dict.update(self.disclosure_concepts)  # Add disclosures first
        self.concept_dict.update(self.statement_concepts)  # Override with statements
        
        # Debug: Final check for SalesRevenueAutomotive
        for dict_name, concepts_dict in [("statement_concepts", self.statement_concepts), 
                                       ("disclosure_concepts", self.disclosure_concepts),
                                       ("concept_dict", self.concept_dict)]:
            for qname in concepts_dict:
                if 'SalesRevenueAutomotive' in qname:
                    logger.debug(f"Found SalesRevenueAutomotive in {dict_name}: {qname}")
        
        logger.info(f"\nProcessed {len(self.statement_concepts)} statement concepts and {len(self.disclosure_concepts)} disclosure concepts")

    @staticmethod
    def get_presentation_networks(taxonomy):
        """Extracts presentation networks from a taxonomy by examining linkbases and base sets"""
        logger.info("\nAccessing presentation networks...")
        
        # First check if presentation linkbases are loaded
        presentation_linkbases = []
        presentation_networks = []
        for lb_location, lb in taxonomy.linkbases.items():
            # Check if this is a presentation linkbase by looking at the file name
            if '_pre.xml' in lb_location.lower():
                presentation_linkbases.append(lb)
                #logger.info(f"Found presentation linkbase: {lb_location}")
                # Debug information about the linkbase
                #logger.info(f"Linkbase type: {type(lb)}, attributes: {dir(lb)}")
                # if hasattr(lb, 'links'):
                #     logger.info(f"Number of links: {len(lb.links)}")
                    #for link in lb.links:
                    #    #logger.debug(f"Link type: {type(link)}, tag: {getattr(link, 'tag', 'No tag')}")
                
        #(threshold_gb=16)
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
                        #logger.debug(f"Found presentation base_set: {key}")
                        presentation_networks.append(base_set)
                elif isinstance(key, str) and 'presentation' in key.lower():
                    #logger.debug(f"Found presentation base_set: {key}")
                    presentation_networks.append(base_set)
            #(threshold_gb=16)
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
                                    logger.debug("Added presentation link to networks")
                                
                                # Also add any presentation arcs
                                if hasattr(link, 'arcs'):
                                    for arc in link.arcs:
                                        if 'presentation' in str(getattr(arc, 'tag', '')).lower():
                                            presentation_networks.append(arc)
                                            logger.debug("Added presentation arc to networks")
                    
                    if presentation_networks:
                        logger.info(f"Built {len(presentation_networks)} networks from linkbases")
                        return presentation_networks
                #(threshold_gb=16)
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

    def _process_network_dimensions(self, network, statement_name):
        concepts = get_network_details(self.tax, network, self.reporter)
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
                logger.debug(f"Found dimension: {dimension}")
            if current_dimension and 'Member' in node_name:
                allowed_members[current_dimension].add(node_name)
                logger.debug(f"Added member {node_name} to dimension {current_dimension}")
            for child_dict in node_dict.get('children', []):
                process_table_structure(child_dict, current_dimension)
        
        for root in root_concepts:
            process_table_structure(root)
        
        
        self.statement_dimensions[statement_name] = {
            'dimensions': allowed_dimensions,
            'members': allowed_members
        }

    def populate_concept_df(self):
        """Creates DataFrame from concept dictionaries and adds calculation information"""
        # Flatten the nested dictionaries into a list of concept infos
        all_concepts = []
        
        # Add statement concepts
        for statement_name, concepts in self.statement_concepts.items():
            all_concepts.extend(concepts)
            
        # Add disclosure concepts
        for disclosure_name, concepts in self.disclosure_concepts.items():
            all_concepts.extend(concepts)
            
        # Create DataFrame
        if all_concepts:
            import pandas as pd
            self.concept_df = pd.DataFrame(all_concepts)
            self.concept_df.loc[:, 'statement_type'] = self.concept_df['statement_name'].map(self.statement_types)
            
            # Ensure segment columns exist
            segment_columns = [
                'segment_axis', 'segment_axis_member',
                'segment_dimension', 'segment_dimension_member',
                'has_dimensions', 'dimension_count'
            ]
            for col in segment_columns:
                if col not in self.concept_df.columns:
                    self.concept_df.loc[:, col] = None
            
            # Create enhanced link_df with segment information
            self.link_df = self.concept_df.copy()
            
            # Add calculation information
            calc_df = tax_calc_df(self.tax)
            if not calc_df.empty:
                # First normalize statement names in both DataFrames
                self.link_df.loc[:, 'statement_name_norm'] = self.link_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
                calc_df.loc[:, 'role_name_norm'] = calc_df['role_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
                
                # Group calculation relationships by role and concept
                calc_by_role_parent = calc_df.groupby(['role_name_norm', 'from_qname'])[['to_qname', 'weight']].apply(
                    lambda x: dict(zip(x['to_qname'], x['weight']))
                ).to_dict()
                
                calc_by_role_child = calc_df.groupby(['role_name_norm', 'to_qname'])[['from_qname', 'weight']].apply(
                    lambda x: dict(zip(x['from_qname'], x['weight']))
                ).to_dict()
                
                # Now add calculation flags
                self.link_df.loc[:, 'is_calc_parent'] = self.link_df.apply(
                    lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_parent, 
                    axis=1
                )
                
                self.link_df.loc[:, 'is_calc_child'] = self.link_df.apply(
                    lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_child, 
                    axis=1
                )
                
                # Add calculation role information
                def get_calc_roles(row, calc_df):
                    return list(calc_df[
                        (calc_df['from_qname'] == row['concept_qname']) | 
                        (calc_df['to_qname'] == row['concept_qname'])
                    ]['role_name'].unique())
                
                self.link_df.loc[:, 'calc_roles'] = self.link_df.apply(
                    lambda row: get_calc_roles(row, calc_df), axis=1
                )
                
                # Add detailed calculation relationships
                def get_calc_details(row):
                    key = (row['statement_name_norm'], row['concept_qname'])
                    children = calc_by_role_parent.get(key, {})
                    parents = calc_by_role_child.get(key, {})
                    
                    return {
                        'calc_children': list(children.keys()),
                        'calc_parents': list(parents.keys()),
                        'calc_children_weights': [v for k, v in children.items()],
                        'calc_children_weights_str': ' + '.join([f"({v:+g}) * {k}" for k, v in children.items()]) if children else '',
                        'calc_children_weights_dict': children,
                        'calc_parents_weights': [v for k, v in parents.items()],
                        'calc_parents_weights_str': ' + '.join([f"({v:+g}) * {k}" for k, v in parents.items()]) if parents else '',
                        'calc_parents_weights_dict': parents,
                        'num_calc_children': len(children),
                        'num_calc_parents': len(parents),
                        'is_summation': len(children) > 1,  # Concept sums multiple children
                        'is_component': len(parents) > 0,   # Concept is part of a sum
                        'has_negative_weight': any(v < 0 for v in children.values()) or any(v < 0 for v in parents.values()),
                        'all_positive_weights': all(v > 0 for v in children.values()) and all(v > 0 for v in parents.values()),
                        'weight_types': ', '.join(set(
                            [f"child:{v:+g}" for v in children.values()] + 
                            [f"parent:{v:+g}" for v in parents.values()]
                        ))
                    }
                
                # Apply calculation details to DataFrame
                calc_details = self.link_df.apply(get_calc_details, axis=1)
                for col, values in pd.DataFrame(calc_details.tolist()).items():
                    self.link_df.loc[:, col] = values
                
                # Add calculation hierarchy information
                def get_calc_hierarchy_info(row, calc_df):
                    concept = row['concept_qname']
                    role_matches = calc_df[calc_df['role_name_norm'] == row['statement_name_norm']]
                    
                    # Find all ancestors (parents of parents)
                    def get_ancestors(qname, visited=None):
                        if visited is None:
                            visited = set()
                        if qname in visited:
                            return set()
                        visited.add(qname)
                        parents = set(role_matches[role_matches['to_qname'] == qname]['from_qname'])
                        ancestors = set()
                        for parent in parents:
                            ancestors.update(get_ancestors(parent, visited))
                        return parents.union(ancestors)
                    
                    # Find all descendants (children of children)
                    def get_descendants(qname, visited=None):
                        if visited is None:
                            visited = set()
                        if qname in visited:
                            return set()
                        visited.add(qname)
                        children = set(role_matches[role_matches['from_qname'] == qname]['to_qname'])
                        descendants = set()
                        for child in children:
                            descendants.update(get_descendants(child, visited))
                        return children.union(descendants)
                    
                    ancestors = get_ancestors(concept)
                    descendants = get_descendants(concept)
                    
                    return {
                        'calc_ancestors': list(ancestors),
                        'calc_descendants': list(descendants),
                        'calc_hierarchy_level': len(ancestors),  # Number of levels above this concept
                        'is_calc_root': len(ancestors) == 0 and len(descendants) > 0,  # Top-level calculation concept
                        'is_calc_leaf': len(descendants) == 0 and len(ancestors) > 0,  # Bottom-level calculation concept
                    }
                
                # Apply calculation hierarchy information
                hierarchy_info = self.link_df.apply(
                    lambda row: get_calc_hierarchy_info(row, calc_df), axis=1
                )
                for col, values in pd.DataFrame(hierarchy_info.tolist()).items():
                    self.link_df.loc[:, col] = values
                
                #logger.debug(f"Added enhanced calculation information to link_df")
        else:
            logger.warning("No concepts found to create DataFrame")

    def is_valid_concept(self, concept_qname):
        """
        Checks if a concept exists in any presentation network.
        
        Args:
            concept_qname: The QName of the concept to check
            
        Returns:
            bool: True if concept exists in any network, False otherwise
        """
        # Check in flat concept dictionary for quick lookup
        return concept_qname in self.concept_dict
        
    def get_concept_info(self, concept_qname):
        """
        Gets detailed information about a concept.
        
        Args:
            concept_qname: The QName of the concept
            
        Returns:
            dict: Concept information including network context, or None if not found
        """
        # First try quick lookup in concept_dict
        if concept_qname in self.concept_dict:
            return self.concept_dict[concept_qname]
            
        # If not found, do an exhaustive search through all networks
        # This is a fallback in case concept_dict is not in sync
        for statement_name, concepts in self.statement_concepts.items():
            for concept in concepts:
                if concept['concept_qname'] == concept_qname:
                    return concept
                    
        for disclosure_name, concepts in self.disclosure_concepts.items():
            for concept in concepts:
                if concept['concept_qname'] == concept_qname:
                    return concept
                    
        return None
        
    def get_concepts_by_statement(self, statement_name):
        """
        Gets all concepts for a specific statement/disclosure.
        
        Args:
            statement_name: Name of the statement or disclosure
            
        Returns:
            list: List of concept information dictionaries, or empty list if not found
        """
        # Check in statement concepts first
        if statement_name in self.statement_concepts:
            return self.statement_concepts[statement_name]
            
        # Then check in disclosure concepts
        if statement_name in self.disclosure_concepts:
            return self.disclosure_concepts[statement_name]
            
        return []
        
    def get_statement_names(self):
        """
        Gets all statement names in the taxonomy.
        
        Returns:
            list: List of statement names
        """
        return list(self.statement_concepts.keys())
        
    def get_disclosure_names(self):
        """
        Gets all disclosure names in the taxonomy.
        
        Returns:
            list: List of disclosure names
        """
        return list(self.disclosure_concepts.keys())

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
        if self.name_sop:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nIncome Statement: {self.name_sop}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.name_sop].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo income statement found'
        if self.name_sfp:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nBalance Sheet: {self.name_sfp}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.name_sfp].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo balance sheet found'
        if self.name_scf:
            if self.concept_df is not None and not self.concept_df.empty:
                info_str += f'\nCash Flow: {self.name_scf}:\n' + self.concept_df.loc[self.concept_df.statement_name==self.name_scf].to_string()
            else:
                info_str += f'\nself.concept_df.empty'
        else:
            info_str += f'\nNo cash flow statement found'
        return info_str
    
    def _is_primary_statement(self, role_name):
        """Determine if a role represents a primary statement; 
        try DocumentAndEntityInformation"""
        statement_keywords = [r'balance', r'operations', r'income', r'cash flow', r'cashflow', r'equity', r'financial position', r'financialposition', r'statement', r'DocumentAndEntityInformation']
        disclosure_keywords = [r'disclosure', r'notes', r'details', r'schedule', r'policies', "table"]
        
        role_lower = role_name.lower()
        return any(
            re.search(keyword, role_lower, flags=re.IGNORECASE) for keyword in statement_keywords) and \
            re.search("Statement|DocumentAndEntityInformation|balancesheet|coverpage|consolidate", role_lower, flags=re.IGNORECASE)  and \
               not any(re.search(keyword, role_lower, flags=re.IGNORECASE) for keyword in disclosure_keywords)


    def _validate_segment(self, segment_data, statement_name):
        """
        Validate segment data against statement's allowed dimensions.
        A fact with dimensions should only be included in a statement if:
        1. The statement allows dimensions AND
        2. The specific dimensions and members are allowed in that statement
        Otherwise, the fact belongs in disclosures.
        
        Args:
            segment_data: Dictionary of dimension:member pairs
            statement_name: Name of the statement to validate against
            
        Returns:
            bool: True if segment is valid for this statement, False otherwise
        """
        # If no segment data, fact is valid for primary statement
        if not segment_data:
            return True
            
        # Get allowed dimensions and members for this statement
        statement_dims = self.statement_dimensions.get(statement_name, {})
        allowed_dimensions = statement_dims.get('dimensions', set())
        allowed_members = statement_dims.get('members', {})
        
        # For each dimension in the segment data
        for dimension, member in segment_data.items():
            # Check if dimension is allowed
            if dimension not in allowed_dimensions:
                return False
                
            # Check if member is allowed for this dimension
            if dimension in allowed_members:
                if member not in allowed_members[dimension]:
                    return False
                    
        return True

    def is_valid_segment(self, concept_qname, segment_data, statement_name=None):
        """
        Check if a segment is valid for a concept in a specific statement context.
        
        Args:
            concept_qname: The concept's QName
            segment_data: Dictionary of dimension:member pairs
            statement_name: Optional statement name to check against
            
        Returns:
            bool: True if the segment is valid for this concept/statement combination
        """
        if not statement_name:
            # If no statement specified, check all statements
            for statement in self.statement_concepts:
                if self._validate_segment(segment_data, statement):
                    return True
            for disclosure in self.disclosure_concepts:
                if self._validate_segment(segment_data, disclosure):
                    return True
            return False
            
        # Validate against specific statement
        return self._validate_segment(segment_data, statement_name)

class StatementOfOperations:
    """Class encapsulating Statement of Operations (SOP) constants and patterns."""
    
    # Ordered list of sections in the statement
    SECTIONS = [
        'REV_COGS_GP',           # Revenue, Cost of Goods Sold, Gross Profit
        'OP_EXP_OP_INC',         # Operating Expenses and Income
        'INT_SPECIAL_PRET',      # Interest, Special Items, Pretax Income
        'INT_SPECIAL_PRET_TAXES_NI',  # Interest, Special Items, Pretax, Taxes, Net Income
        'NI_MINORITY_EPS'        # Net Income, Minority Interest, EPS
    ]
    
    # Mapping of exact US-GAAP concept matches to account types
    EXACT_MATCHES = {
        'REV': [
            'us-gaap:Revenues',
            'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
            'us-gaap:SalesRevenueNet',
            'us-gaap:SalesRevenueGoodsNet',
            'us-gaap:RevenueFromContractWithCustomer'
        ],
        'COGS': [
            'us-gaap:CostOfGoodsAndServicesSold',
            'us-gaap:CostOfRevenue',
            'us-gaap:CostOfGoodsSold',
            'us-gaap:CostOfServices'
        ],
        'GP': [
            'us-gaap:GrossProfit',
            'us-gaap:GrossMargin'
        ],
        'OP_EXP': [
            'us-gaap:OperatingExpenses',
            'us-gaap:SellingGeneralAndAdministrativeExpense',
            'us-gaap:ResearchAndDevelopmentExpense',
            'us-gaap:DepreciationDepletionAndAmortization',
            'us-gaap:ProvisionForDoubtfulAccounts',
            'us-gaap:BusinessCombinationAcquisitionAndIntegrationCosts',
            'us-gaap:MarketingExpense',
            'us-gaap:AdvertisingExpense'
        ],
        'OP_INC': [
            'us-gaap:OperatingIncomeLoss',
            'us-gaap:IncomeLossFromContinuingOperations',
            'us-gaap:IncomeLossFromOperations'
        ],
        'SPI': [
            'us-gaap:GainsLossesOnExtinguishmentOfDebt',
            'us-gaap:ImpairmentOfInvestments',
            'us-gaap:GainLossOnSaleOfOtherAssets',
            'us-gaap:AssetImpairmentCharges',
            'us-gaap:RestructuringCosts',
            'us-gaap:NonoperatingIncomeExpense',
            'us-gaap:IncomeLossFromEquityMethodInvestments',
            'us-gaap:GainLossOnInvestments',
            'us-gaap:GainLossOnDispositionOfAssets',
            'us-gaap:BusinessCombinationAcquisitionRelatedCosts'
        ],
        'PRET': [
            'us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
            'us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes'
        ],
        'TAX': [
            'us-gaap:IncomeTaxExpenseBenefit',
            'us-gaap:IncomeTaxesPaid',
            'us-gaap:IncomeTaxesPaidNet'
        ],
        'NI': [
            'us-gaap:NetIncomeLoss',
            'us-gaap:ProfitLoss',
            'us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic'
        ],
        'MIN_INT': [
            'us-gaap:NetIncomeLossAttributableToNoncontrollingInterest',
            'us-gaap:IncomeLossAttributableToNoncontrollingInterest'
        ],
        'EPS': [
            'us-gaap:EarningsPerShareBasic',
            'us-gaap:EarningsPerShareDiluted',
            'us-gaap:WeightedAverageNumberOfSharesOutstandingBasic',
            'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding'
        ]
    }
    
    # Regex patterns for fuzzy matching concept names and labels
    PATTERNS = {
        'REV': [
            r'revenue', r'sale.*net', r'turnover', r'fee.*income', 
            r'net.*sales',  
            # this is not revenue: r'operating.*income(?!.*expense)',
            r'contract.*revenue', r'service.*revenue'
        ],
        'COGS': [
            r'cost.*good.*sold', r'cost.*revenue', r'cost.*sale', 
            r'direct.*cost', r'product.*cost', r'cost.*service'
        ],
        'GP': [
            r'gross.*profit', r'gross.*margin', r'gross.*income'
        ],
        'OP_EXP': [
            r'operating.*expense', r'selling.*expense', r'general.*administrative',
            r'marketing.*expense', r'research.*development', r'depreciation',
            r'amortization', r'sg.*a', r'labor.*expense', r'personnel.*cost',
            r'provision.*credit.*loss', r'provision.*doubtful.*account',
            r'acquisition.*integration.*cost', r'advertising.*expense'
        ],
        'OP_INC': [
            r'operating.*income', r'operating.*profit', r'operating.*earning',
            r'operating.*loss', r'income.*from.*operation', r'operating.*result'
        ],
        'INT_INC': [
            r'interest.*income', r'interest.*revenue', r'investment.*income'
        ],
        'INT_EXP': [
            r'interest.*expense', r'interest.*cost', r'financing.*cost'
        ],
        'SPECIAL': [
            r'special.*item', r'extraordinary', r'unusual', r'restructuring',
            r'discontinued.*operation', r'impairment', r'disposal', 
            r'write.*off', r'write.*down', r'gain.*sale', r'loss.*sale',
            r'other.*income', r'other.*expense', r'other.*gain', r'other.*loss',
            r'equity.*earning', r'equity.*loss', r'debt.*extinguishment',
            r'acquisition.*related.*cost', r'integration.*cost'
        ],
        'PRET': [
            r'.*before.*tax.*', r'pretax.*income', r'pre.*tax.*income',
            r'income.*before.*tax', r'earning.*before.*tax'
        ],
        'TAX': [
            r'income.*tax.*', r'tax.*expense', r'tax.*benefit', 
            r'tax.*provision', r'deferred.*tax', r'tax.*paid'
        ],
        'NI': [
            r'net.*income', r'net.*loss', r'profit.*loss', r'net.*earning',
            r'net.*result', r'income.*after.*tax', r'net.*profit'
        ],
        'MIN_INT': [
            r'minority.*interest', r'non.*controlling.*interest', 
            r'attributable.*to.*non.*controlling'
        ],
        'EPS': [
            r'per.*share', r'earnings.*per.*share', r'.*eps.*',
            r'diluted.*share', r'basic.*share', r'weighted.*average.*share'
        ]
    }
    
    # Mapping of account types to their sections
    ACCOUNT_TYPE_TO_SECTION = {
        'REV': 'REV_COGS_GP',
        'COGS': 'REV_COGS_GP',
        'GP': 'REV_COGS_GP',
        'OP_EXP': 'OP_EXP_OP_INC',
        'OP_INC': 'OP_EXP_OP_INC',
        'INT_INC': 'INT_SPECIAL_PRET',
        'INT_EXP': 'INT_SPECIAL_PRET',
        'SPECIAL': 'INT_SPECIAL_PRET',
        'PRET': 'INT_SPECIAL_PRET',
        'TAX': 'INT_SPECIAL_PRET_TAXES_NI',
        'NI': 'INT_SPECIAL_PRET_TAXES_NI',
        'MIN_INT': 'NI_MINORITY_EPS',
        'EPS': 'NI_MINORITY_EPS'
    }
    
    @staticmethod
    def matches_pattern(text, pattern_list):
        """Check if text matches any pattern in the list."""
        if not isinstance(text, str):
            return False
        text = text.lower().replace('_', '').replace('-', '')
        return any(re.search(pattern, text) for pattern in pattern_list)
    
    @classmethod
    def get_section_for_account_type(cls, account_type):
        """Get the section for a given account type."""
        return cls.ACCOUNT_TYPE_TO_SECTION.get(account_type)
    
    @classmethod
    def is_valid_section(cls, section):
        """Check if a section name is valid."""
        return section in cls.SECTIONS
    
    @classmethod
    def is_valid_account_type(cls, account_type):
        """Check if an account type is valid."""
        return account_type in cls.ACCOUNT_TYPE_TO_SECTION


def get_network_details(tax, network, reporter=None):
    """Processes a presentation network to extract concept details and relationships."""
    concepts = []
    statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
    logger.debug(f"Extracting details from network: {statement_name}")
    
    try:
        if isinstance(network, XLink):
            logger.debug("Processing XLink network")
            concepts_by_label = {}
            concept_info_by_qname = {}  # Track concept info by qname to avoid duplicates
            
            # Process locators to get concepts
            if hasattr(network, 'locators'):
                for label, loc in network.locators.items():
                    if re.search("mem:\/\w", loc.href):
                        loc.href = re.sub(r'mem:\/', 'mem://', loc.href)
                    concept = tax.get_concept_by_href(loc.href)
                    if concept:
                        concepts_by_label[label] = concept
                        # Also store with _lbl suffix for label lookup
                        concepts_by_label[f"{label}_lbl"] = concept
                        
                        # Add concept info for each locator concept
                        concept_qname = str(concept.qname)
                        if concept_qname not in concept_info_by_qname:
                            concept_info = {
                                'name': concept.name,
                                'qname': concept_qname,
                                'label': concept.get_label() if hasattr(concept, 'get_label') else 'N/A',
                                'order': None,  # Will be updated from arc if found
                                'parent_qname': None,  # Will be updated from arc if found
                                'preferred_label': None  # Will be updated from arc if found
                            }
                            concept_info_by_qname[concept_qname] = concept_info
                            concepts.append(concept_info)
            
            # Process arcs to update relationships and orders
            if hasattr(network, 'arcs_from'):
                for arc_from, arc_list in network.arcs_from.items():
                    for arc in arc_list:
                        from_concept = (concepts_by_label.get(arc.xl_from) or 
                                      concepts_by_label.get(f"{arc.xl_from}_lbl"))
                        to_concept = (concepts_by_label.get(arc.xl_to) or 
                                    concepts_by_label.get(f"{arc.xl_to}_lbl"))
                        
                        if from_concept and to_concept:
                            to_qname = str(to_concept.qname)
                            from_qname = str(from_concept.qname)
                            
                            # Update concept info with relationship details
                            if to_qname in concept_info_by_qname:
                                concept_info_by_qname[to_qname].update({
                                    'order': getattr(arc, 'order', None),
                                    'parent_qname': from_qname,
                                    'preferred_label': getattr(arc, 'preferred_label', None)
                                })
                            
                            # Ensure from_concept info is also present
                            if from_qname not in concept_info_by_qname:
                                concept_info = {
                                    'name': from_concept.name,
                                    'qname': from_qname,
                                    'label': from_concept.get_label() if hasattr(from_concept, 'get_label') else 'N/A',
                                    'order': None,
                                    'parent_qname': None,
                                    'preferred_label': None
                                }
                                concept_info_by_qname[from_qname] = concept_info
                                concepts.append(concept_info)
            
            # Sort concepts by order if available
            concepts.sort(key=lambda x: float(x['order']) if x['order'] is not None else float('inf'))
            
            return concepts
        
        logger.warning(f"Network {statement_name} is not an XLink instance")
        return []
        
    except Exception as e:
        logger.error(f"Error processing network {statement_name}: {str(e)}")
        logger.debug("Exception details:", exc_info=True)
        return []

def analyze_statement_section(section_facts, fact_df, section_name="SOP"):
    """
    Analyze a specific section of a statement, providing metrics about its composition and complexity.
    
    Args:
        section_facts (pd.DataFrame): DataFrame containing facts for the specific section
        fact_df (pd.DataFrame): Complete fact DataFrame for additional context
        section_name (str): Name of the section being analyzed
        
    Returns:
        dict: Analysis results including:
            - num_line_items: Total number of line items in the section
            - num_non_standard: Number of non-standard (non-us-gaap) concepts
            - num_with_axes: Number of facts using axes
            - num_with_dimensions: Number of facts using dimensions
            - top_concepts: List of top 5 concepts by absolute value
            - section_size: Total absolute value of all facts in section
            - relative_size: Size relative to total statement size
            - complexity_score: Based on number of non-standard and dimensional items
    """
    result = {
        "section_name": section_name,
        "num_line_items": 0,
        "num_non_standard": 0,
        "num_with_axes": 0,
        "num_with_dimensions": 0,
        "top_concepts": [],
        "section_size": 0.0,
        "relative_size": 0.0,
        "complexity_score": 0.0
    }
    
    if section_facts.empty:
        return result
        
    # Basic line item count
    result["num_line_items"] = len(section_facts)
    
    # Non-standard concepts analysis
    non_standard = section_facts[~section_facts.concept_qname.str.startswith('us-gaap:', na=False)]
    result["num_non_standard"] = len(non_standard)
    
    # Dimensional usage
    result["num_with_axes"] = len(section_facts[section_facts.segment_axis.notna()])
    result["num_with_dimensions"] = len(section_facts[section_facts.has_dimensions == True])
    
    # Value analysis
    if 'value' in section_facts.columns:
        # Convert values to numeric where possible
        section_facts = section_facts.copy()  # Create a copy to avoid SettingWithCopyWarning
        section_facts.loc[:, 'abs_value'] = pd.to_numeric(section_facts['value'], errors='coerce').abs()
        
        # Calculate section size
        result["section_size"] = section_facts['abs_value'].sum()
        
        # Get top concepts by absolute value
        top_concepts = (section_facts
            .sort_values('abs_value', ascending=False)
            .head(5)
            [['concept_qname', 'label', 'value', 'abs_value']]
            .to_dict('records'))
        result["top_concepts"] = top_concepts
        
        # Calculate relative size if we have the full statement facts
        if fact_df is not None and not fact_df.empty:
            fact_df_copy = fact_df.copy()  # Create a copy to avoid SettingWithCopyWarning
            fact_df_copy.loc[:, 'abs_value'] = pd.to_numeric(fact_df_copy['value'], errors='coerce').abs()
            total_statement_size = fact_df_copy['abs_value'].sum()
            if total_statement_size > 0:
                result["relative_size"] = result["section_size"] / total_statement_size
    
    # Complexity score (simple heuristic)
    # Higher score for more non-standard and dimensional items
    base_complexity = 1.0
    non_standard_weight = result["num_non_standard"] / max(result["num_line_items"], 1)
    dimensional_weight = (result["num_with_axes"] + result["num_with_dimensions"]) / (2 * max(result["num_line_items"], 1))
    result["complexity_score"] = base_complexity + non_standard_weight + dimensional_weight
    
    return result
    

def find_concept_by_pattern_and_value(sop_df, *, account_types, exclude_patterns=None, top_k=1, 
                                      check_absolute_value=True, ascending=False,
                                      return_values=False):
    """Find the top K concepts based on account type matching and value magnitude.
    
    Args:
        sop_df (pd.DataFrame): DataFrame containing SOP concepts and values
        account_types (list): List of account types to match (e.g., ['REV'], ['NI'])
        exclude_patterns (list, optional): Additional patterns to exclude
        top_k (int, optional): Number of top concepts to return. Defaults to 1.
        check_absolute_value (bool, optional): Whether to use absolute values for sorting. Defaults to True.
        ascending (bool, optional): Sort order for values. Defaults to False.
        return_values (bool, optional): Whether to return values along with concepts. Defaults to False.
        
    Returns:
        If top_k == 1 and not return_values:
            str: concept_qname of the matched concept with largest value
        If top_k > 1 or return_values:
            list: List of dicts containing concept info (qname, value, abs_value)
    """
    # Find matching concepts using identify_sop_section_for_concept
    sop_df = sop_df.copy()  # Create a copy to avoid SettingWithCopyWarning
    sop_df.loc[:, 'abs_value'] = pd.to_numeric(sop_df['value'], errors='coerce').abs()
    matching_concepts = []
    for idx, row in sop_df.iterrows():
        section, account_type = identify_sop_section_for_concept(
            str(row['concept_name']), 
            str(row['label'])
        )
        if account_type in account_types:
            # Check additional exclude patterns if provided
            if exclude_patterns:
                exclude_str = '|'.join(exclude_patterns)
                if re.search(exclude_str, str(row['concept_name']), re.IGNORECASE):
                    continue
            matching_concepts.append(row)
    
    if not matching_concepts:
        return None if top_k == 1 and not return_values else []
    
    # Convert to DataFrame for easier processing
    matching_df = pd.DataFrame(matching_concepts)
    
    # Group by concept and get max value
    concept_max = matching_df.groupby("concept_qname").agg({
        'abs_value': 'max',
        'value': 'first'  # Take the first value for each concept
    })
    
    # Sort based on check_absolute_value parameter
    sort_column = 'abs_value' if check_absolute_value else 'value'
    concept_max = concept_max.sort_values(sort_column, ascending=ascending)
    
    if concept_max.empty:
        return None if top_k == 1 and not return_values else []
    
    # If only want top 1 concept and no values, return just the qname
    if top_k == 1 and not return_values:
        return concept_max.index.tolist()[0]
    
    # Otherwise return list of dicts with concept info
    if not return_values:
        return concept_max.index[:top_k].tolist()
    
    results = []
    for qname in concept_max.index[:top_k]:
        results.append({
            'concept_qname': qname,
            'value': concept_max.loc[qname, 'value'],
            'abs_value': concept_max.loc[qname, 'abs_value']
        })
    
    return results


def analyze_non_standard_concepts(stm_df, statement_type="SOP"):
    """Analyze concepts that don't use the us-gaap namespace."""
    non_standard_concepts = stm_df[
        ~stm_df.concept_qname.str.startswith('us-gaap:', na=False)
    ]
    return {
        f"num_non_standard_concepts_{statement_type.lower()}": len(non_standard_concepts)
    }

def analyze_dimensional_usage(fact_df, stm_df, statement_type="SOP"):
    """Analyze the usage of dimensions and axes in SOP facts."""
    sop_facts = fact_df[
        fact_df.concept_qname.isin(stm_df.concept_qname) &
        (fact_df.statement_type == statement_type) 
    ]
    
    facts_with_axes = sop_facts[sop_facts.segment_axis.notna()]
    facts_with_dimensions = sop_facts[sop_facts.has_dimensions == True]
    
    return {
        f"num_facts_with_axes_{statement_type.lower()}": len(facts_with_axes),
        f"num_facts_with_dimensions_{statement_type.lower()}": len(facts_with_dimensions)
    }

def identify_sop_section_for_concept(concept_name, label, order=None, classified_sections=None):
    """
    Identify the section and account type for a single concept in the Statement of Operations.
    
    Args:
        concept_name (str): Name of the concept (can be us-gaap or company-specific)
        label (str): Label of the concept
        order (float, optional): Order of the concept in the statement
        classified_sections (dict, optional): Dictionary of already classified sections with their order ranges
        
    Returns:
        tuple: (section, account_type) where:
            - section: Section identifier (REV_COGS_GP, OP_EXP_OP_INC, etc.)
            - account_type: Specific account type within the section (REV, COGS, GP, etc.)
    """
    # First try exact matches with US-GAAP concepts
    for account_type, concepts in StatementOfOperations.EXACT_MATCHES.items():
        if concept_name in concepts:
            return StatementOfOperations.ACCOUNT_TYPE_TO_SECTION[account_type], account_type
    
    # Combine concept name and label for pattern matching
    # Remove us-gaap: prefix if present for better matching
    concept_text = concept_name.replace('us-gaap:', '') if concept_name else ''
    text = f"{concept_text} {label}"
    
    # Try pattern matching
    for account_type, pattern_list in StatementOfOperations.PATTERNS.items():
        if StatementOfOperations.matches_pattern(text, pattern_list):
            return StatementOfOperations.ACCOUNT_TYPE_TO_SECTION[account_type], account_type
    
    # If no match but we have order information and classified sections
    if order is not None and classified_sections is not None:
        for section, (min_order, max_order) in classified_sections.items():
            if min_order <= order <= max_order:
                # Try to infer account type based on surrounding concepts
                return section, 'OTHER'
    
    # If still no match, log for analysis
    logger.debug(f"Unclassified concept: {concept_name} with label: {label}")
    return None, None



def get_current_fact_df(fact_df, min_fact_ratio=0.5, max_periods=8, num_current_periods=2):
    """Get facts from the most recent reporting periods.
    
    Args:
        fact_df (pd.DataFrame): DataFrame containing all facts
        min_fact_ratio (float): Minimum ratio relative to 75th percentile of facts per period
        max_periods (int): Maximum number of periods to consider
        num_current_periods (int): Number of most recent periods to return
        
    Returns:
        pd.DataFrame: Facts from the most recent periods
        
    Notes:
        This function may be moved to openesef.engines.tax_pres.py    
    """
    if fact_df.empty:
        logger.warning("Empty fact_df provided to get_current_fact_df")
        return fact_df.copy()
        
    if "period_string" not in fact_df.columns:
        logger.error("fact_df missing required column 'period_string'")
        return fact_df.copy()

    # Count facts per period
    context_counts = fact_df.groupby("period_string").size().sort_values(ascending=False).reset_index()
    
    # Filter periods with sufficient facts
    min_facts = context_counts[0].quantile(0.75) * min_fact_ratio
    context_counts = context_counts.loc[context_counts[0] >= min_facts]
    
    # Get most recent periods from top periods
    context_counts = context_counts.head(max_periods)
    context_counts.sort_values("period_string", inplace=True, ascending=True)
    current_contexts = context_counts.tail(num_current_periods).period_string.tolist()
    
    logger.debug(f"Selected {len(current_contexts)} current periods: {current_contexts}")
    
    return fact_df.loc[fact_df.period_string.isin(current_contexts)].copy()

def merge_statement_dataframe(link_df, current_fact_sop_df, statement_type="SOP"):
    """Extract Statement of Operations (SOP) dataframe by merging link and fact data.
    
    Args:
        link_df (pd.DataFrame): DataFrame containing presentation linkbase information
        current_fact_df (pd.DataFrame): DataFrame containing current period facts
        
    Returns:
        pd.DataFrame: Merged DataFrame containing SOP facts with presentation information
    
    Notes:
        This function may be moved to openesef.engines.tax_pres.py        
    """
    if link_df.empty or current_fact_sop_df.empty:
        logger.warning("Empty DataFrame provided to get_sop_dataframe")
        return pd.DataFrame()

    # Validate required columns
    required_link_cols = ["statement_type", "concept_qname", "segment_axis", "segment_axis_member"]
    required_fact_cols = ["concept_qname", "segment_axis", "segment_axis_member"]
    
    missing_link_cols = [col for col in required_link_cols if col not in link_df.columns]
    missing_fact_cols = [col for col in required_fact_cols if col not in current_fact_sop_df.columns]
    
    if missing_link_cols or missing_fact_cols:
        logger.debug(f"Missing columns - link_df: {missing_link_cols}, fact_df: {missing_fact_cols}")
        #return pd.DataFrame()

    # Extract SOP concepts
    #statement_type="SOP"
    stm_df = link_df[link_df.statement_type == statement_type].copy()
    #stm_df.loc[stm_df.concept_qname == "us-gaap:EarningsPerShareBasic", ["concept_qname", "label", "statement_type", "order"]]# just one;
    #current_fact_sop_df.loc[current_fact_sop_df.concept_qname == "us-gaap:EarningsPerShareBasic", ["fact_index", "label", "statement_type","segment_dimension_member", "value"]]
    
    if stm_df.empty:
        logger.warning("No SOP concepts found in link_df")
        return pd.DataFrame()

    # Merge with facts
    pre_merge_count = len(stm_df)
    merge_cols = ["concept_qname"]
    
    # Only include segment columns in merge if they contain data
    if "segment_axis" in stm_df.columns and "segment_axis" in current_fact_sop_df.columns:
        if stm_df.segment_axis.notna().any() and current_fact_sop_df.segment_axis.notna().any():
            merge_cols.extend(["segment_axis", "segment_axis_member"])

    if "segment_dimension" in stm_df.columns and "segment_dimension" in current_fact_sop_df.columns:
        if stm_df.segment_axis.notna().any() and current_fact_sop_df.segment_axis.notna().any():
            merge_cols.extend(["segment_dimension", "segment_dimension_member"])

    
    stm_df_merged = stm_df.merge(
        current_fact_sop_df[ merge_cols + ["fact_index", "value"]],
        on=merge_cols,
        how="inner"
    )
    #stm_df_merged.sort_values(by="fact_index")[["fact_index", "label",  "value"]].head(60)
    
    post_merge_count = len(stm_df_merged)
    logger.debug(f"SOP merge results: {pre_merge_count} concepts, {post_merge_count} facts after merge")
    
    return stm_df_merged




def get_child_concepts(reporter, network, concept, taxonomy, visited=None): # not used?
    """Recursively get all child concepts of a given concept
    not called by anyone else?"""
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





def process_children(reporter, network, parent, concepts, grandparent_qname): #not used?
    """
    Recursively process children of a concept; 
    but is this function called by anyone else?
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


def build_concept_hierarchy(network, tax, reporter):
    """Build a dictionary mapping concepts to their list of parents"""
    concept_parents = {}
    concepts = get_network_details(tax, network, reporter)
    
    # First pass - build direct parent relationships
    direct_parents = {}
    for concept in concepts:
        qname = concept['qname']
        parent_qname = concept.get('parent_qname')
        if parent_qname:
            if qname not in direct_parents:
                direct_parents[qname] = set()
            direct_parents[qname].add(parent_qname)
    
    # Second pass - build full parent hierarchy
    def get_all_parents(qname, visited=None):
        if visited is None:
            visited = set()
        if qname in visited:
            return []
        visited.add(qname)
        
        parents = list(direct_parents.get(qname, set()))
        for parent in list(parents):  # Create a copy of parents list to iterate
            grandparents = get_all_parents(parent, visited)
            parents.extend(grandparents)
        return parents
    
    # Build full hierarchy for each concept
    for qname in direct_parents:
        concept_parents[qname] = get_all_parents(qname)
        
    return concept_parents

 


def tax_calc_df(tax):
    """
    Returns a dataframe of the calculation network
    """
    calc_arcs = [(k, v) for k, v in tax.base_sets.items() if k[0] == 'calculationArc']
    #print(f"Found {len(calc_arcs)} calculation arcs")

    # for key in tax.base_sets:
    #     if key[0] == 'calculationArc':
    #         print(f"Found calculation arc with role: {key[1]}")

    # Check for calculation arcs in base_sets

    # Print details of each calculation arc
    calc_records = []
    for key, link in calc_arcs:
        # rel_count = len(getattr(link, 'relationships', []))
        # print(f"\nRole: {key[1]}")
        # print(f"Number of relationships: {rel_count}")
        role = key[1]
        role_name = role.split("/")[-1]
        # Print first few relationships if any exist
        if hasattr(link, 'relationships'):
            for rel in link.relationships:#[:3]:  # Show first 3 relationships
                #print(f"  {rel['from'].qname} -> {rel['to'].qname} (weight: {rel['weight']})   order {rel['order']}")
                record = {
                    'role': role,
                    'role_name': role_name,
                    'from_qname': str(rel['from'].qname),
                    'to_qname': str(rel['to'].qname),
                    'weight': rel['weight'],
                    'order': rel['order']
                }
                calc_records.append(record)

    calc_df = pd.DataFrame(calc_records)
    #print(calc_df)
    return calc_df


def is_numeric(x):
    try:
        float(x)
        return True
    except (ValueError, TypeError):
        return False


def process_statement_section(current_facts, statement_name):
    """
    Process facts for a specific statement section and add statement appearance info.
    
    Args:
        current_facts (pd.DataFrame): DataFrame containing current period facts
        statement_name (str): Name of the statement section to process
        
    Returns:
        pd.DataFrame: Processed facts for the statement section with added appearance info
    """
    section_facts = current_facts[current_facts.statement_name == statement_name].copy()
    
    if not section_facts.empty:
        section_facts['all_statements'] = section_facts['statement_appearances'].apply(lambda x: ', '.join(x))
        section_facts.sort_values('order', na_position='last', inplace=True)
        
    return section_facts

def analyze_statement_section(section_facts, fact_df, section_name="SOP"):
    """
    Analyze a specific section of a statement, providing metrics about its composition and complexity.
    
    Args:
        section_facts (pd.DataFrame): DataFrame containing facts for the specific section
        fact_df (pd.DataFrame): Complete fact DataFrame for additional context
        section_name (str): Name of the section being analyzed
        
    Returns:
        dict: Analysis results including:
            - num_line_items: Total number of line items in the section
            - num_non_standard: Number of non-standard (non-us-gaap) concepts
            - num_with_axes: Number of facts using axes
            - num_with_dimensions: Number of facts using dimensions
            - top_concepts: List of top 5 concepts by absolute value
            - section_size: Total absolute value of all facts in section
            - relative_size: Size relative to total statement size
            - complexity_score: Based on number of non-standard and dimensional items
    """
    result = {
        "section_name": section_name,
        "num_line_items": 0,
        "num_non_standard": 0,
        "num_with_axes": 0,
        "num_with_dimensions": 0,
        "top_concepts": [],
        "section_size": 0.0,
        "relative_size": 0.0,
        "complexity_score": 0.0
    }
    
    if section_facts.empty:
        return result
        
    # Basic line item count
    result["num_line_items"] = len(section_facts)
    
    # Non-standard concepts analysis
    non_standard = section_facts[~section_facts.concept_qname.str.startswith('us-gaap:', na=False)]
    result["num_non_standard"] = len(non_standard)
    
    # Dimensional usage
    result["num_with_axes"] = len(section_facts[section_facts.segment_axis.notna()])
    result["num_with_dimensions"] = len(section_facts[section_facts.has_dimensions == True])
    
    # Value analysis
    if 'value' in section_facts.columns:
        # Convert values to numeric where possible
        section_facts = section_facts.copy()  # Create a copy to avoid SettingWithCopyWarning
        section_facts.loc[:, 'abs_value'] = pd.to_numeric(section_facts['value'], errors='coerce').abs()
        
        # Calculate section size
        result["section_size"] = section_facts['abs_value'].sum()
        
        # Get top concepts by absolute value
        top_concepts = (section_facts
            .sort_values('abs_value', ascending=False)
            .head(5)
            [['concept_qname', 'label', 'value', 'abs_value']]
            .to_dict('records'))
        result["top_concepts"] = top_concepts
        
        # Calculate relative size if we have the full statement facts
        if fact_df is not None and not fact_df.empty:
            fact_df_copy = fact_df.copy()  # Create a copy to avoid SettingWithCopyWarning
            fact_df_copy.loc[:, 'abs_value'] = pd.to_numeric(fact_df_copy['value'], errors='coerce').abs()
            total_statement_size = fact_df_copy['abs_value'].sum()
            if total_statement_size > 0:
                result["relative_size"] = result["section_size"] / total_statement_size
    
    # Complexity score (simple heuristic)
    # Higher score for more non-standard and dimensional items
    base_complexity = 1.0
    non_standard_weight = result["num_non_standard"] / max(result["num_line_items"], 1)
    dimensional_weight = (result["num_with_axes"] + result["num_with_dimensions"]) / (2 * max(result["num_line_items"], 1))
    result["complexity_score"] = base_complexity + non_standard_weight + dimensional_weight
    
    return result

# Add example usage function at the end of the file
if __name__ == "__main__":
    """Example of how to use the TaxonomyPresentation class with order information"""
    from openesef.edgar.loader import load_xbrl_filing
    # Load a filing
    # filing_url = "https://www.sec.gov/Archives/edgar/data/1004980/0001004980-22-000009.txt"
    # Process memory usage (20.1GB) exceeded threshold (8GB) for https://www.sec.gov/Archives/edgar/data/766704/0000766704-22-000013.txt
    #xid, tax = load_xbrl_filing(filing_url="https://www.sec.gov/Archives/edgar/data/766704/0000766704-22-000013.txt", memory_threshold_gb=16)
    #xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)
    filing_url = "https://www.sec.gov/Archives/edgar/data/1013871/0001013871-22-000010.txt"
    #filing_url = "https://www.sec.gov/Archives/edgar/data/1172298/0001415889-15-002688.txt"
    xid, tax = load_xbrl_filing(filing_url=filing_url, memory_threshold_gb=16)
    fact_df = ins_facts(xid, tax)
    fact_df.sort_values(by='fact_index', inplace=True)
    fact_df["val_mln"] = fact_df["value"].apply(lambda x: float(x)/1000000 if is_numeric(x) and float(x) > 1000000 else x)
    
    current_period_string = fact_df.period_string.value_counts().index[0]
    current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)
    
    t_pres = TaxonomyPresentation(tax)
    link_df = t_pres.link_df
    # Get facts for each major statement
    so_facts = process_statement_section(current_facts, t_pres.name_sop)
    fp_facts = process_statement_section(current_facts, t_pres.name_sfp)
    cf_facts = process_statement_section(current_facts, t_pres.name_scf)
    
    
    # Export Statement of Operations
    if not so_facts.empty:
        so_facts[["fact_index", "concept_qname","label", "value", "value_mln", "segment_axis", 
                 "appears_in_statements", "all_statements", "order", "fact_included"]].to_excel("/tmp/apple_2020_so.xlsx")
        
        
        #fact_df = fact_df.loc[fact_df.fact_included ]
        current_period_string = fact_df.period_string.value_counts().index[0]
        current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)

        current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop) & (current_facts['fact_included']==True) , [ 'concept_qname',  ]]#.head(30)
        current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop) & (current_facts['fact_included']==True) , [ 'label', "segment_axis","segment_axis_member", "value" ]]#.head(30)
        current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop)].shape #45
        t_pres.concept_df.loc[t_pres.concept_df.statement_name==t_pres.name_sop].shape #25
        current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop)  , ].to_excel("/tmp/apple_2020_so_current.xlsx")
        #print(f"\nStatement of Operations exported with {len(so_facts)} facts")
        # Print concepts that appear in multiple statements
        multi_statement_so = so_facts[so_facts.appears_in_statements > 1]
        # if not multi_statement_so.empty:
        #     print("Concepts appearing in multiple statements:")
        #     print(multi_statement_so[["concept_name", "all_statements"]].drop_duplicates())

        # Get calculation information for a specific statement
        so_concepts = t_pres.link_df[t_pres.link_df.statement_name == t_pres.name_sop]

        # View concepts that are calculation parents
        calc_parents = so_concepts[so_concepts.is_calc_parent]
        
        # View calculation relationships for a specific concept
        concept_info = so_concepts[so_concepts.concept_name == 'NetIncomeLoss']
        print("Children:", concept_info.calc_children.iloc[0])
        print("Children weights:", concept_info.calc_children_weights_str.iloc[0])
        print("Children weights:", concept_info.calc_children_weights_dict.iloc[0])
        concept_info.to_dict()
    
    # Export Balance Sheet (Financial Position)
    if not fp_facts.empty:
        fp_facts[["fact_index", "concept_name", "value", "value_mln", "segment_axis",
                 "appears_in_statements", "all_statements", "order", "fact_included"]].to_excel("/tmp/apple_2020_bs.xlsx")
        #print(f"\nBalance Sheet exported with {len(fp_facts)} facts")
        # Print concepts that appear in multiple statements
        multi_statement_fp = fp_facts[fp_facts.appears_in_statements > 1]
        # if not multi_statement_fp.empty:
        #     print("Concepts appearing in multiple statements:")
        #     print(multi_statement_fp[["concept_name", "all_statements"]].drop_duplicates())
    
    # Export Cash Flow Statement
    if not cf_facts.empty:
        cf_facts[["fact_index", "concept_name", "value", "value_mln", "segment_axis",
                 "appears_in_statements", "all_statements", "order", "fact_included"]].to_excel("/tmp/apple_2020_cf.xlsx")
        #print(f"\nCash Flow Statement exported with {len(cf_facts)} facts")
        # Print concepts that appear in multiple statements
        multi_statement_cf = cf_facts[cf_facts.appears_in_statements > 1]
        # if not multi_statement_cf.empty:
        #     print("Concepts appearing in multiple statements:")
        #     print(multi_statement_cf[["concept_name", "all_statements"]].drop_duplicates())
    
    # Summary statistics
    logger.info("\n".join([
        f"\nSummary Statistics:",
        f"Total facts in current period: {len(current_facts)}",
        f"Facts in Statement of Operations: {len(so_facts)}",
        f"Facts in Balance Sheet: {len(fp_facts)}",
        f"Facts in Cash Flow Statement: {len(cf_facts)}"
    ]))
    
    # Analyze each section of the statement
    so_analysis = analyze_statement_section(so_facts, fact_df, "Statement of Operations")
    fp_analysis = analyze_statement_section(fp_facts, fact_df, "Statement of Financial Position")
    cf_analysis = analyze_statement_section(cf_facts, fact_df, "Statement of Cash Flows")
    
    # Print analysis results
    for analysis in [so_analysis, fp_analysis, cf_analysis]:
        if analysis["num_line_items"] > 0:
            print(f"\nAnalysis for {analysis['section_name']}:")
            print(f"Line items: {analysis['num_line_items']}")
            print(f"Non-standard concepts: {analysis['num_non_standard']}")
            print(f"Dimensional usage: {analysis['num_with_dimensions']} items")
            print(f"Relative size: {analysis['relative_size']:.2%}")
            print(f"Complexity score: {analysis['complexity_score']:.2f}")
            print("\nTop concepts by value:")
            for concept in analysis["top_concepts"][:3]:  # Show top 3
                print(f"- {concept['concept_qname']}: {concept['value']}")
    
if False:    
    # # Continue with the other analysis examples...
    #                 items = list(ref_context.segment.items()) 
    #                 if items:
    #                     dimension, member = items[0]
    # Example 1: Show all appearances of NetIncomeLoss
    ni_facts = current_facts[current_facts.concept_name == "NetIncomeLoss"].copy()
    ni_facts['all_statements'] = ni_facts['statement_appearances'].apply(lambda x: ', '.join(x))
    ni_facts[["fact_index", "concept_name", "value", "statement_name", "all_statements", 
              "appears_in_statements", "fact_included"]].to_excel("/tmp/ni_all_statements.xlsx")
    
    # Example 2: Show facts that appear in multiple statements
    multi_statement_facts = current_facts[current_facts.appears_in_statements > 1].copy()
    multi_statement_facts['all_statements'] = multi_statement_facts['statement_appearances'].apply(lambda x: ', '.join(x))
    multi_statement_facts[["fact_index", "concept_name", "value", "statement_name", 
                          "all_statements", "appears_in_statements", "fact_included"]].to_excel("/tmp/multi_statement_facts.xlsx")
    
    # Example 3: Enhanced statement of operations export with statement appearance info
    so_facts = current_facts[current_facts.statement_name == t_pres.name_sop].copy()
    so_facts['all_statements'] = so_facts['statement_appearances'].apply(lambda x: ', '.join(x))
    so_facts[["fact_index", "concept_name", "value", "segment_axis", "period_end", 
              "fact_included", "appears_in_statements", "all_statements"]].to_excel("/tmp/apple_2020_so_enhanced.xlsx")
    
    # Example 4: Detailed analysis of a specific concept
    def analyze_concept(concept_name):
        concept_facts = current_facts[current_facts.concept_name == concept_name].copy()
        if not concept_facts.empty:
            # Add all_statements column first
            concept_facts['all_statements'] = concept_facts['statement_appearances'].apply(lambda x: ', '.join(x))
            
            print(f"\nAnalysis of concept: {concept_name}")
            print(f"Appears in {concept_facts.iloc[0].appears_in_statements} statements:")
            print(f"Statements: {', '.join(concept_facts.iloc[0].statement_appearances)}")
            print(f"Primary statement: {concept_facts.iloc[0].statement_name}")
            print(f"Fact included: {concept_facts.iloc[0].fact_included}")
            #print("\nValues across contexts:")
            return concept_facts[["fact_index", "value", "period_string", "statement_name", 
                                "all_statements", "appears_in_statements", "fact_included"]]
        return pd.DataFrame()
    
    # Example usage of analyze_concept
    # ni_analysis = analyze_concept("NetIncomeLoss")
    # if not ni_analysis.empty:
    #     print(ni_analysis)  # Print to console first
    #     ni_analysis.to_excel("/tmp/ni_analysis.xlsx")
    
    # Example 5: Summary of concepts by number of statement appearances
    statement_appearance_summary = current_facts.groupby('concept_name').agg({
        'appears_in_statements': 'first',
        'statement_appearances': 'first'
    }).reset_index()
    
    statement_appearance_summary['all_statements'] = statement_appearance_summary['statement_appearances'].apply(lambda x: ', '.join(x))
    statement_appearance_summary = statement_appearance_summary.sort_values('appears_in_statements', ascending=False)
    statement_appearance_summary.to_excel("/tmp/statement_appearance_summary.xlsx")
    
    print(current_facts.loc[(current_facts['statement_name'] == t_pres.name_sop)  , ['fact_index', 'concept_name', 'label', "segment_axis", 'value', 'period_end', 'fact_included']].head(30))
