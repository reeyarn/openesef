"""


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
                logger.info(f"\nProcessing network: {statement_name} (Primary: {is_primary})")
            
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
            self.concept_df['statement_type'] = self.concept_df['statement_name'].map(self.statement_types)
            
            # Ensure segment columns exist
            segment_columns = [
                'segment_axis', 'segment_axis_member',
                'segment_dimension', 'segment_dimension_member',
                'has_dimensions', 'dimension_count'
            ]
            for col in segment_columns:
                if col not in self.concept_df.columns:
                    self.concept_df[col] = None
            
            # Create enhanced link_df with segment information
            self.link_df = self.concept_df.copy()
            
            # Add calculation information
            calc_df = tax_calc_df(self.tax)
            if not calc_df.empty:
                # First normalize statement names in both DataFrames
                self.link_df['statement_name_norm'] = self.link_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
                calc_df['role_name_norm'] = calc_df['role_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
                
                # Group calculation relationships by role and concept
                calc_by_role_parent = calc_df.groupby(['role_name_norm', 'from_qname'])[['to_qname', 'weight']].apply(
                    lambda x: dict(zip(x['to_qname'], x['weight']))
                ).to_dict()
                
                calc_by_role_child = calc_df.groupby(['role_name_norm', 'to_qname'])[['from_qname', 'weight']].apply(
                    lambda x: dict(zip(x['from_qname'], x['weight']))
                ).to_dict()
                
                # Now add calculation flags
                self.link_df['is_calc_parent'] = self.link_df.apply(
                    lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_parent, 
                    axis=1
                )
                
                self.link_df['is_calc_child'] = self.link_df.apply(
                    lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_child, 
                    axis=1
                )
                
                # Add calculation role information
                def get_calc_roles(row, calc_df):
                    return list(calc_df[
                        (calc_df['from_qname'] == row['concept_qname']) | 
                        (calc_df['to_qname'] == row['concept_qname'])
                    ]['role_name'].unique())
                
                self.link_df['calc_roles'] = self.link_df.apply(
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
                    self.link_df[col] = values
                
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
                    self.link_df[col] = values
                
                logger.info(f"Added enhanced calculation information to link_df")
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
        logger.debug(f"\nValidating segment for statement: {statement_name}")
        logger.debug(f"Segment data: {segment_data}")
        
        # If this is a primary statement and there's segment data, generally reject
        # unless explicitly allowed by the statement's dimension configuration
        if self._is_primary_statement(statement_name):
            # No segment data is always valid for primary statements
            if not segment_data:
                logger.debug("No segment data - valid for primary statement")
                return True
                
            # If there is segment data, it's only valid if explicitly configured
            statement_dims = self.statement_dimensions.get(statement_name)
            if not statement_dims or not statement_dims.get('dimensions'):
                logger.debug(f"Primary statement {statement_name} does not allow dimensions")
                return False
                
            # Check if all dimensions and members are explicitly allowed
            for dimension, member in segment_data.items():
                if dimension not in statement_dims['dimensions']:
                    logger.debug(f"Dimension {dimension} not allowed in primary statement")
                    return False
                    
                allowed_members = statement_dims['members'].get(dimension, set())
                if allowed_members and member not in allowed_members:
                    logger.debug(f"Member {member} not allowed for dimension {dimension} in primary statement")
                    return False
        
        # For disclosures, we're more permissive with segments
        else:
            logger.debug("Non-primary statement/disclosure - accepting segments")
            return True
            
        logger.debug("Segment validation passed")
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
    
    logger.info(f"Selected {len(current_contexts)} current periods: {current_contexts}")
    
    return fact_df.loc[fact_df.period_string.isin(current_contexts)].copy()

def merge_statement_dataframe(link_df, current_fact_df, statement_type="SOP"):
    """Extract Statement of Operations (SOP) dataframe by merging link and fact data.
    
    Args:
        link_df (pd.DataFrame): DataFrame containing presentation linkbase information
        current_fact_df (pd.DataFrame): DataFrame containing current period facts
        
    Returns:
        pd.DataFrame: Merged DataFrame containing SOP facts with presentation information
    
    Notes:
        This function may be moved to openesef.engines.tax_pres.py        
    """
    if link_df.empty or current_fact_df.empty:
        logger.warning("Empty DataFrame provided to get_sop_dataframe")
        return pd.DataFrame()

    # Validate required columns
    required_link_cols = ["statement_type", "concept_qname", "segment_axis", "segment_axis_member"]
    required_fact_cols = ["concept_qname", "segment_axis", "segment_axis_member"]
    
    missing_link_cols = [col for col in required_link_cols if col not in link_df.columns]
    missing_fact_cols = [col for col in required_fact_cols if col not in current_fact_df.columns]
    
    if missing_link_cols or missing_fact_cols:
        logger.error(f"Missing columns - link_df: {missing_link_cols}, fact_df: {missing_fact_cols}")
        return pd.DataFrame()

    # Extract SOP concepts
    stm_df = link_df[link_df.statement_type == statement_type].copy()
    
    if stm_df.empty:
        logger.warning("No SOP concepts found in link_df")
        return pd.DataFrame()

    # Merge with facts
    pre_merge_count = len(stm_df)
    merge_cols = ["concept_qname"]
    
    # Only include segment columns in merge if they contain data
    if stm_df.segment_axis.notna().any() and current_fact_df.segment_axis.notna().any():
        merge_cols.extend(["segment_axis", "segment_axis_member"])
    
    stm_df = stm_df.merge(
        current_fact_df,
        on=merge_cols,
        how="inner"
    )
    
    post_merge_count = len(stm_df)
    logger.info(f"SOP merge results: {pre_merge_count} concepts, {post_merge_count} facts after merge")
    
    return stm_df



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
                    'label': item.Concept.get_label() if hasattr(item.Concept, 'get_label') else 'N/A',
                    'period_type': item.Concept.period_type if hasattr(item.Concept, 'period_type') else 'N/A',
                    'balance': item.Concept.balance if hasattr(item.Concept, 'balance') else 'N/A',
                    'level': item.Level,
                    'children': get_child_concepts(reporter, network, item.Concept, taxonomy, visited)
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

 

def ins_facts(xid, tax):
    """Extract facts from instance"""
    if xid is None or tax is None:
        logger.warning("xid or tax is None")
        return None
    if xid.xbrl is None:
        logger.warning("xid.xbrl is None")
        return None
    #tracemalloc.start()  # Start tracing
    t_pres = TaxonomyPresentation(tax)
    
    periods_dict = xid.identify_reporting_contexts()
    logger.info(f"Starting fact extraction with {len(xid.xbrl.facts)} facts and {len(periods_dict)} valid contexts")

    # Create a dictionary to store all statement appearances for each concept
    concept_statement_appearances = {}
    primary_statement_names = list()
    disclosure_names = list()
    
    # Before the fact_list loop, build concept hierarchies for each network
    network_hierarchies = {}
    pres_networks = TaxonomyPresentation.get_presentation_networks(tax)
    for network in pres_networks:
        statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
        network_hierarchies[statement_name] = build_concept_hierarchy(network, tax, t_pres.reporter)
    
        # First pass - record all statement appearances for each concept
        # for network in pres_networks:
        statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
        concepts = get_network_details(tax, network, t_pres.reporter)
        
        for concept in concepts:
            concept_qname = concept['qname']
            # Initialize list if concept not seen before
            if concept_qname not in concept_statement_appearances:
                concept_statement_appearances[concept_qname] = []
            
            # Get the concept object to access its labels
            concept_obj = tax.concepts_by_qname.get(concept_qname)
            preferred_label = None
            if concept_obj and hasattr(concept_obj, 'labels'):
                # Try terse label first
                terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
                if terse_role in concept_obj.labels:
                    preferred_label = concept_obj.get_label(role=terse_role, lang='en-US')
                # If no terse label, try standard label
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
    #(threshold_gb=16)
    #mem_tops(top_n=10)
    logger.info("Finished checking network with concepts")
    fact_list = []
    fact_list_disclosure = []
    #included_facts ={}
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
        
        # try:
        #     # Get the preferred label for display
        #     preferred_label = None
        #     if hasattr(concept, 'labels'):
        #         # Try terse label first
        #         terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
        #         if terse_role in concept.labels:
        #             preferred_label = concept.get_label(role=terse_role, lang='en-US')
        #         # If no terse label, try standard label
        #         if not preferred_label or preferred_label == 'N/A':
        #             preferred_label = concept.get_label(lang='en-US')
            
        #     # Safely convert numeric values
        #     if fact.value is not None:
        #         if fact.unit_ref is not None and "usd" in fact.unit_ref.lower() and fact.decimals == "-6":
        #             raw_value = safe_numeric_conversion(fact.value)
        #             value_mln = raw_value / 1000000 if raw_value is not None else None
        #         else:
        #             value_mln = None
                    
        #         # For text storage, limit length and handle numeric values
        #         if "text" in concept.name.lower():
        #             stored_value = fact.value[:100]  # Truncate long text
        #         else:
        #             stored_value = safe_numeric_conversion(fact.value, default=str(fact.value))
        #     else:
        #         stored_value = None
        #         value_mln = None

        #     # Get segment data from context
        #     segment_data = {}
        #     segment_member_label = None
        #     ref_context = xid.xbrl.contexts.get(fact.context_ref)
        #     if ref_context and hasattr(ref_context, 'segment') and ref_context.segment:
        #         items = list(ref_context.segment.items())
        #         if items:
        #             dimension, member = items[0]
        #             member_value = member.text if hasattr(member, 'text') else str(member)
        #             segment_data[str(dimension)] = member_value
                    
        #             # Get the label for the segment member
        #             member_qname = str(member_value)
        #             member_concept = tax.concepts_by_qname.get(member_qname)
        #             if member_concept and hasattr(member_concept, 'labels'):
        #                 terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
        #                 if terse_role in member_concept.labels:
        #                     segment_member_label = member_concept.get_label(role=terse_role, lang='en-US')
        #                 if not segment_member_label or segment_member_label == 'N/A':
        #                     segment_member_label = member_concept.get_label(lang='en-US')

        #     fact_dict = {
        #         # Basic fact information
        #         'fact_index': fact.fact_index,
        #         'concept_name': concept.name,
        #         'concept_qname': concept_qname,
        #         "unit_ref": fact.unit_ref,
        #         "decimals": fact.decimals,
        #         'value': stored_value,
        #         'value_mln': value_mln,
        #         'context_ref': fact.context_ref,
                
        #         # Context information from periods_dict
        #         'period_string': periods_dict.get(fact.context_ref, {}).get("period_string"),
        #         'period_type': concept.period_type if hasattr(concept, 'period_type') else None,
        #         'period_start': periods_dict.get(fact.context_ref, {}).get("period_start"),
        #         'period_end': periods_dict.get(fact.context_ref, {}).get("period_end"),
        #         'period_instant': periods_dict.get(fact.context_ref, {}).get("period_instant"),
        #         'entity_scheme': periods_dict.get(fact.context_ref, {}).get("entity_scheme"),
        #         'entity_identifier': periods_dict.get(fact.context_ref, {}).get("entity_identifier"),
                
        #         # Segment information as separate columns
        #         'segment_axis': None,
        #         'segment_axis_member': None,
        #         'segment_dimension': None,
        #         'segment_dimension_member': None,
        #         'has_dimensions': False,
        #         'dimension_count': 0,
                
        #         # Statement information from the selected appearance
        #         'statement_name': statement_info['statement_name'],
        #         'statement_role': statement_info['statement_role'],
        #         'primary_statement': statement_info['is_primary_statement'],
        #         'appears_in_statements': len(statement_appearances),
        #         'statement_appearances': [app['statement_name'] for app in statement_appearances],
        #         'statement_label': (f"{statement_info['statement_name']} "
        #                         f"({statement_info['statement_role']})") if statement_info['statement_name'] else None,
        #         'parent_qname': statement_info['parent_qname'],
        #         'label': (f"{segment_member_label}" if segment_member_label else 
        #                     preferred_label if preferred_label else 
        #                     statement_info['label']),
        #         'order': statement_info['order'],
                
        #         # Set fact_included based on primary statement status and segment validation
        #         'fact_included': statement_info['is_primary_statement'] and t_pres._validate_segment(segment_data, statement_info['statement_name'])
        #     }

        #     # Get additional context information directly from the context object
        #     ref_context = xid.xbrl.contexts.get(fact.context_ref)
        #     if ref_context:
        #         # Update period information
        #         fact_dict['period'] = ref_context.get_period_string()
        #         fact_dict['period_type'] = concept.period_type if hasattr(concept, 'period_type') else None
        #         fact_dict['period_start'] = ref_context.period_start
        #         fact_dict['period_end'] = ref_context.period_end
        #         fact_dict['period_instant'] = ref_context.period_instant if hasattr(ref_context, 'period_instant') else None
                
        #         # Update entity information
        #         fact_dict['entity_scheme'] = ref_context.entity_scheme if hasattr(ref_context, 'entity_scheme') else None
        #         fact_dict['entity_identifier'] = ref_context.entity_identifier if hasattr(ref_context, 'entity_identifier') else None
                
        #         # Update segment information
        #         if hasattr(ref_context, 'segment') and ref_context.segment:
        #             items = list(ref_context.segment.items())
        #             if items:
        #                 dimension, member = items[0]
        #                 member_value = member.text if hasattr(member, 'text') else str(member)
        #                 fact_dict['segment_axis'] = str(dimension)
        #                 fact_dict['segment_axis_member'] = member_value
        #                 fact_dict['segment_dimension'] = str(dimension)
        #                 fact_dict['segment_dimension_member'] = member_value
                
        #         # Update scenario information
        #         if hasattr(ref_context, 'scenario') and ref_context.scenario:
        #             scenario_info = {}
        #             for dimension, member in ref_context.scenario.items():
        #                 scenario_info[str(dimension)] = member.text if hasattr(member, 'text') else str(member)
        #             fact_dict['scenario'] = scenario_info
        #         else:
        #             fact_dict['scenario'] = None

        #     # Add concept parents
        #     statement_name = fact_dict['statement_name']
        #     concept_qname = fact_dict['concept_qname']
        #     fact_dict['concept_parents'] = network_hierarchies.get(statement_name, {}).get(concept_qname, [])

        #     fact_dict['fact_id'] = key
        #     if statement_name in disclosure_names:
        #         fact_list_disclosure.append(fact_dict)

        except Exception as e:
            logger.error(f"Error processing fact {key}: {str(e)}")
            continue
    logger.info(f"Finished extracting facts for disclosures with {len(fact_list_disclosure)} facts")
    #mem_tops(top_n=30)            
    #check_memory_usage(threshold_gb=16)
    # Create DataFrames from collected facts
    fact_df = pd.DataFrame(fact_list)
    fact_df['statement_name_norm'] = fact_df['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)

    fact_df_disclosure = pd.DataFrame(fact_list_disclosure)
    fact_df_disclosure['statement_name_norm'] = fact_df_disclosure['statement_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)

    # Ensure numeric columns are properly typed
    numeric_columns = ['value_mln']
    for col in numeric_columns:
        if col in fact_df.columns:
            fact_df[col] = pd.to_numeric(fact_df[col], errors='coerce')
        if col in fact_df_disclosure.columns:
            fact_df_disclosure[col] = pd.to_numeric(fact_df_disclosure[col], errors='coerce')

    # Process calculations if available
    calc_df = tax_calc_df(tax)
    if not calc_df.empty:
        # Add statement name normalization to both DataFrames
        # This helps with matching since role_name and statement_name may have slight differences
        calc_df['role_name_norm'] = calc_df['role_name'].str.lower().str.replace('[^a-z0-9]', '', regex=True)
        
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
        fact_df['is_calc_parent'] = fact_df.apply(
            lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_parent, 
            axis=1
        )
        
        fact_df['is_calc_child'] = fact_df.apply(
            lambda row: (row['statement_name_norm'], row['concept_qname']) in calc_by_role_child, 
            axis=1
        )
        
        fact_df['calc_children_with_weights'] = fact_df.apply(get_calc_children_with_weights, axis=1)
        fact_df['calc_parents_with_weights'] = fact_df.apply(get_calc_parents_with_weights, axis=1)
        
        # Extract just the list of children and parents (without weights)
        fact_df['calc_children'] = fact_df['calc_children_with_weights'].apply(lambda x: list(x.keys()))
        fact_df['calc_parents'] = fact_df['calc_parents_with_weights'].apply(lambda x: list(x.keys()))

    # Update fact_included based on ID ranges for each primary statement
    fact_df.sort_values(by='fact_index', inplace=True)
    fact_df_disclosure.sort_values(by='fact_index', inplace=True)
    fact_df["is_disclosure"] = False
    fact_df_disclosure["is_disclosure"] = True
    
    # Get concepts that only appear in statements or disclosures
    only_statement_concepts = [concept for concept in t_pres.statement_concepts if concept not in t_pres.disclosure_concepts]
    only_disclosure_concepts = [concept for concept in t_pres.disclosure_concepts if concept not in t_pres.statement_concepts]
    
    # Process each primary statement separately
    for primary_statement_name in primary_statement_names:
        # Get facts for this statement
        statement_facts = fact_df[fact_df['statement_name'] == primary_statement_name]
        
        if statement_facts.empty:
            continue
            
        # Update fact_included based on both statement membership and segment validation
        mask = (fact_df['statement_name'] == primary_statement_name)
        fact_df.loc[mask, 'fact_included'] = fact_df.loc[mask].apply(
            lambda row: (
                # Only include facts that:
                # 1. Are in a primary statement AND
                # 2. Have no dimensions (segment_axis is None) OR
                # 3. Have explicitly allowed dimensions for this statement
                row['primary_statement'] and 
                (pd.isna(row['segment_axis']) or 
                 t_pres._validate_segment(
                     {row['segment_axis']: row['segment_axis_member']} if pd.notna(row['segment_axis']) else {},
                     primary_statement_name
                 ))
            ),
            axis=1
        )

        # Find statement-only concepts in this statement
        # statement_only_facts = statement_facts[statement_facts['concept_qname'].isin(only_statement_concepts)]
        # min_statement_id = statement_only_facts['fact_index'].min() if not statement_only_facts.empty else float('inf')
        
        # # Find disclosure-only concepts that appear after this statement's facts
        # statement_disclosure_facts = fact_df_disclosure[
        #     (fact_df_disclosure['concept_qname'].isin(only_disclosure_concepts)) &
        #     (fact_df_disclosure['fact_index'] >= min_statement_id)
        # ]
        # min_disclosure_id = statement_disclosure_facts['fact_index'].min() if not statement_disclosure_facts.empty else float('inf')

        # fact_df.loc[mask & (fact_df['fact_index'] >= min_disclosure_id), 'fact_included'] = False
        #fact_df.loc[mask & (fact_df['fact_index'] < min_disclosure_id), 'fact_included'] = True
        


    fact_df = pd.concat([fact_df, fact_df_disclosure])
    fact_df["fact_included"] = np.where(fact_df["fact_included"].isna(), False, fact_df["fact_included"])
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
    print(calc_df)
    return calc_df


def is_numeric(x):
    try:
        float(x)
        return True
    except (ValueError, TypeError):
        return False





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
    so_facts = current_facts[current_facts.statement_name == t_pres.name_sop].copy()
    fp_facts = current_facts[current_facts.statement_name == t_pres.name_sfp].copy()
    cf_facts = current_facts[current_facts.statement_name == t_pres.name_scf].copy()
    
    # Add statement appearance info to each
    for df in [so_facts, fp_facts, cf_facts]:
        if not df.empty:
            df['all_statements'] = df['statement_appearances'].apply(lambda x: ', '.join(x))
            df.sort_values('order', na_position='last', inplace=True)
    
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
