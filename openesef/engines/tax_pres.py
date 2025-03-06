"""
tax_pres.py - Taxonomy Presentation Processing Module

This module provides functionality for processing XBRL taxonomy presentation linkbases and 
extracting structured concept information. It helps organize concepts into statements and 
validates segment/dimension information.

Key Classes:
-----------
TaxonomyPresentation
    Main class that processes taxonomy presentation networks and organizes concepts into 
    primary statements and disclosures.

Key Functions:
-------------
get_presentation_networks(taxonomy)
    Extracts presentation networks from a taxonomy by examining linkbases and base sets.

get_network_details(tax, network, reporter)
    Processes a presentation network to extract concept details and relationships.

get_child_concepts(reporter, network, concept, taxonomy, visited=None)
    Recursively extracts child concepts from a presentation network hierarchy.
    but is this function called by anyone else? 
process_children(reporter, network, parent, concepts, grandparent_qname)
    Helper function to process child concepts in a presentation network.

ins_facts(xid, tax)
    Extracts facts from an XBRL instance document and organizes them based on the 
    presentation structure.

Example Usage:
-------------
# Create a TaxonomyPresentation instance
t_pres = TaxonomyPresentation(taxonomy, reporter)

# Get facts from an instance document
fact_df = ins_facts(xbrl_instance, taxonomy)

# Access statement information
print(t_pres.statement_concepts)  # Concepts in primary statements
print(t_pres.disclosure_concepts)  # Concepts in disclosures
print(t_pres.statement_dimensions)  # Allowed dimensions per statement

Classes:
--------
TaxonomyPresentation:
    Attributes:
        tax: The taxonomy object being processed
        reporter: TaxonomyReporter instance for label handling
        concept_df: DataFrame containing all concepts
        allowed_segments_by_statement: Dict mapping statements to allowed segments
        concept_dict: Dict containing all concepts
        statement_concepts: Dict containing primary statement concepts
        disclosure_concepts: Dict containing disclosure concepts
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

Notes:
------
- The module assumes a standard XBRL taxonomy structure with presentation linkbases
- Primary statements are identified using keyword matching in role names
- Segment validation supports both axis/member and dimension/member terminology
- Period types and other attributes are obtained from the concept definitions
"""

from openesef.util.util_mylogger import setup_logger 
import logging 
import os
import re
import gc
import pandas as pd

from openesef.taxonomy.xlink import XLink
from itertools import chain
import traceback




if __name__=="__main__":
    log_filename= "/tmp/log_main_20250305_p0.log"
    if os.path.exists(log_filename):
        os.remove(log_filename)
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/", full_format=True, formatter_string='%(name)s.%(levelname)s: %(message)s',pid=0)
else:
    logger = logging.getLogger("openesef.engines.tax_pres") 

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
                label = concept.get_label() if hasattr(concept, 'get_label') else None
                self.disclosure_concepts[str(qname)] = {
                    "concept_name": concept.name,
                    "concept_qname": str(qname),
                    "label": label,
                    "statement_name": "Unknown",
                    "statement_role": None,
                    "is_primary_statement": False
                }
            # Copy to main concept dictionary
            self.concept_dict.update(self.disclosure_concepts)
            return
        
        # Process each network
        for network in networks:
            statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
            is_primary = self._is_primary_statement(statement_name)
            logger.info(f"\nProcessing network: {statement_name} (Primary: {is_primary})")
            
            # Process network dimensions
            self._process_network_dimensions(network, statement_name)
            
            # Get concepts using reporter for labels
            concepts = get_network_details(self.tax, network, self.reporter)
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


def get_network_details(tax, network, reporter=None):
    """Extract concept details from a presentation network"""
    concepts = []
    statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
    logger.info(f"Extracting details from network: {statement_name}")
    
    try:
        if isinstance(network, XLink):
            logger.info("Processing XLink network")
            concepts_by_label = {}
            
            # Process locators to get concepts
            if hasattr(network, 'locators'):
                for label, loc in network.locators.items():
                    if "SalesRevenueAutomotive" in label:
                        logger.debug(f"get_network_details Locator {label} href: {loc.href}")
                    # if re.search("^\w", loc.href):
                    #     loc.href = "mem://" + loc.href
                    if re.search("mem:\/\w", loc.href):
                        loc.href = re.sub(r'mem:\/', 'mem://', loc.href)
                    #     logger.debug(f"Locator {label} href: {loc.href}")
                    if "SalesRevenueAutomotive" in label:
                        logger.debug(f"get_network_details Locator updated {label} href: {loc.href}")
                    concept = tax.get_concept_by_href(loc.href)
                    if concept:
                        concepts_by_label[label] = concept
                        # Also store with _lbl suffix for label lookup
                        concepts_by_label[f"{label}_lbl"] = concept
                        if "SalesRevenueAutomotive" in label:
                            logger.debug(f"Found concept for locator {label}: {concept.qname}")
                    else:
                        if "SalesRevenueAutomotive" in label:
                            logger.warning(f"Locator {label} did not resolve to a concept.")
            
            # Process arcs to build relationships
            relationships = []
            if hasattr(network, 'arcs_from'):
                for arc_from, arc_list in network.arcs_from.items():
                    for arc in arc_list:
                        # Try both with and without _lbl suffix
                        from_concept = (concepts_by_label.get(arc.xl_from) or 
                                      concepts_by_label.get(f"{arc.xl_from}_lbl"))
                        to_concept = (concepts_by_label.get(arc.xl_to) or 
                                    concepts_by_label.get(f"{arc.xl_to}_lbl"))
                        
                        if from_concept and to_concept:
                            # Get preferred label if available
                            preferred_label = getattr(arc, 'preferred_label', None)
                            
                            relationships.append({
                                'from': from_concept,
                                'to': to_concept,
                                'order': getattr(arc, 'order', None),
                                'preferred_label': preferred_label
                            })
                            if "SalesRevenueAutomotive" in from_concept.qname or "SalesRevenueAutomotive" in to_concept.qname:
                                logger.debug(f"Found relationship: {from_concept.qname} -> {to_concept.qname}")
            
            # Process relationships to build concept list
            for rel in relationships:
                to_concept = rel['to']
                from_concept = rel['from']
                
                # Get labels for concepts
                for concept in [to_concept, from_concept]:
                    concept_qname = str(concept.qname)
                    if concept_qname not in [c['qname'] for c in concepts]:
                        if "SalesRevenueAutomotive" in concept_qname:
                            logger.debug(f"Processing concept {concept_qname}")
                        concept_info = {
                            'name': concept.name,
                            'qname': concept_qname,
                            'label': concept.get_label() if hasattr(concept, 'get_label') else 'N/A',
                            'order': rel['order'],
                            'parent_qname': str(from_concept.qname) if concept == to_concept else None,
                            'preferred_label': rel['preferred_label']
                        }
                        concepts.append(concept_info)
                        if 'SalesRevenueAutomotive' in concept_qname:
                            logger.info(f"Added SalesRevenueAutomotive concept: {concept_info}")
            
            # Also add any standalone concepts from locators that might not be in relationships
            for label, concept in concepts_by_label.items():
                concept_qname = str(concept.qname)
                if concept_qname not in [c['qname'] for c in concepts]:
                    concept_label = reporter.get_label(str(concept.qname)) if reporter else concept.get_label()
                    concept_info = {
                        'name': concept.name,
                        'qname': concept_qname,
                        'label': concept_label,
                        'order': None,
                        'parent_qname': None
                    }
                    concepts.append(concept_info)
                    if 'SalesRevenueAutomotive' in concept_qname:
                        logger.info(f"Added standalone SalesRevenueAutomotive concept: {concept_info}")
        
        logger.info(f"Found {len(concepts)} concepts in network")
        return concepts
        
    except Exception as e:
        logger.error(f"Error processing network: {str(e)}")
        logger.debug("Exception details:", exc_info=True)
        return []        




def get_presentation_networks(taxonomy):
    """Get presentation networks from taxonomy"""
    logger.info("\nAccessing presentation networks...")
    
    # First check if presentation linkbases are loaded
    presentation_linkbases = []
    presentation_networks = []
    for lb_location, lb in taxonomy.linkbases.items():
        # Check if this is a presentation linkbase by looking at the file name
        if '_pre.xml' in lb_location.lower():
            logger.info(f"Found presentation linkbase: {lb_location}")
            # Debug information about the linkbase
            logger.info(f"Linkbase type: {type(lb)}, attributes: {dir(lb)}")
            if hasattr(lb, 'links'):
                logger.info(f"Number of links: {len(lb.links)}")
                #for link in lb.links:
                #    #logger.debug(f"Link type: {type(link)}, tag: {getattr(link, 'tag', 'No tag')}")
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
                    #logger.debug(f"Found presentation base_set: {key}")
                    presentation_networks.append(base_set)
            elif isinstance(key, str) and 'presentation' in key.lower():
                #logger.debug(f"Found presentation base_set: {key}")
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


def ins_facts(xid, tax):
    """Extract facts from instance"""
    t_pres = TaxonomyPresentation(tax)
    periods_dict = xid.identify_reporting_contexts()
    logger.debug(f"Starting fact extraction with {len(xid.xbrl.facts)} facts and {len(periods_dict)} valid contexts")

    # Create a dictionary to store the first statement appearance for each concept
    concept_first_statement = {}
    
    # First pass - record the first statement appearance for each concept
    for network in get_presentation_networks(tax):
        statement_name = network.role.split('/')[-1] if hasattr(network, 'role') else 'Unknown'
        concepts = get_network_details(tax, network, t_pres.reporter)
        
        for concept in concepts:
            concept_qname = concept['qname']
            # Only store the first appearance
            if concept_qname not in concept_first_statement:
                concept_first_statement[concept_qname] = {
                    'statement_name': statement_name,
                    'statement_role': network.role if hasattr(network, 'role') else None,
                    'is_primary_statement': t_pres._is_primary_statement(statement_name),
                    'order': concept.get('order'),
                    'parent_qname': concept.get('parent_qname'),
                    'label': concept.get('label')
                }

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
        
        # Get concept info from first appearance
        first_statement_info = concept_first_statement.get(concept_qname)
        if not first_statement_info:
            continue
            
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
        if fact.context_ref not in periods_dict:
            invalid_context_count += 1
            if invalid_context_count <= 10 or 'SalesRevenueAutomotive' in concept_qname:
                logger.debug(f"Fact {key}: Context {fact.context_ref} not in valid contexts")
            continue
            
        # Get context information
        ref_context = xid.xbrl.contexts.get(fact.context_ref)
        this_context_dict = periods_dict[fact.context_ref]
        
        # Extract segment data
        segment_axis = None
        segment_axis_member = None
        segment_dimension = None
        segment_dimension_member = None
        
        if ref_context and hasattr(ref_context, 'segment') and ref_context.segment:
            # Get the first (and usually only) dimension-member pair
            items = list(ref_context.segment.items())
            if items:
                dimension, member = items[0]
                member_value = member.text if hasattr(member, 'text') else str(member)
                
                # Store as axis/dimension format
                segment_axis = str(dimension)
                segment_axis_member = member_value
                # Also store as dimension format (alternative naming)
                segment_dimension = str(dimension)
                segment_dimension_member = member_value
                
                if 'SalesRevenueAutomotive' in concept_qname:
                    logger.info(f"  Segment data: axis={segment_axis}, member={segment_axis_member}")

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
        
        is_valid_segment = t_pres._validate_segment({'dimensions': [segment_axis], 'members': [segment_axis_member]} if segment_axis else {}, statement_name)
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
            'fact_index': fact.fact_index,
            'concept_name': concept.name,
            'concept_qname': concept_qname,
            "unit_ref": fact.unit_ref,
            "decimals": fact.decimals,
            'value': fact.value if "text" not in concept.name.lower() else fact.value[:100],
            "value_mln": float(fact.value) / 1000000 if fact.unit_ref is not None and "USD" in fact.unit_ref and fact.decimals == "-6" else None,
            'context_ref': fact.context_ref,
            
            # Context information from periods_dict
            'period_string': this_context_dict.get("period_string"),
            'period_type': concept.period_type if hasattr(concept, 'period_type') else None,
            'period_start': this_context_dict.get("period_start"),
            'period_end': this_context_dict.get("period_end"),
            'period_instant': this_context_dict.get("period_instant"),
            'entity_scheme': this_context_dict.get("entity_scheme"),
            'entity_identifier': this_context_dict.get("entity_identifier"),
            
            # Segment information as separate columns
            'segment_axis': segment_axis,
            'segment_axis_member': segment_axis_member,
            'segment_dimension': segment_dimension,
            'segment_dimension_member': segment_dimension_member,
            'has_dimensions': bool(segment_axis),
            'dimension_count': 1 if segment_axis else 0,
            
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
            
            # Use the first statement appearance information
            'statement_name': first_statement_info['statement_name'],
            'statement_role': first_statement_info['statement_role'],
            'primary_statement': first_statement_info['is_primary_statement'],
            'appears_in_statements': 1 if first_statement_info['statement_name'] else 0,
            'statement_label': (f"{first_statement_info['statement_name']} "
                              f"({first_statement_info['statement_role']})") if first_statement_info['statement_name'] else None,
            'parent_qname': first_statement_info['parent_qname'],
            'label': first_statement_info['label'],
            'order': first_statement_info['order'],
            
            # Inclusion flag based on primary statement status and segment validation
            'fact_included': fact_included
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

        fact_dict['fact_id'] = key
        #fact_dict['fact_id_num'] = int(re.findall(r'\d+', key)[0])  if re.findall(r'\d+', key) else None

        fact_list.append(fact_dict)        

    # Create DataFrame from collected facts
    
    fact_df = pd.DataFrame(fact_list)

    # Figure out the ID range for statement and disclosure respectively by first finding facts that only belong to disclosures and 
    # using their minimum ID as the border.
    # Use that range to determine whether a fact should not belong to any statement.

    fact_df.sort_values(by='fact_index', inplace=True)
    
    only_statement_concepts = [concept for concept in t_pres.statement_concepts if concept not in t_pres.disclosure_concepts]
    only_disclosure_concepts = [concept for concept in t_pres.disclosure_concepts if concept not in t_pres.statement_concepts]
    
    min_statement_id_num = None
    min_disclosure_id_num = None
    if only_statement_concepts:
        only_statement_facts = fact_df[fact_df['concept_qname'].isin(only_statement_concepts)]
        #only_statement_facts.statement_name.value_counts()
        if not only_statement_facts.empty:
            min_statement_id_num = only_statement_facts['fact_index'].min()
        else:
            min_statement_id_num = float('inf')  # If no statement facts, set a high number    
    
    
    if only_disclosure_concepts:
        only_disclosure_facts = fact_df[fact_df['concept_qname'].isin(only_disclosure_concepts)]
        #only_disclosure_facts.statement_name.value_counts()
        if min_statement_id_num:
            only_disclosure_facts = only_disclosure_facts[only_disclosure_facts['fact_index'] >= min_statement_id_num]
        
        if not only_disclosure_facts.empty:
            min_disclosure_id_num = only_disclosure_facts['fact_index'].min()
        else:
            min_disclosure_id_num = float('inf')  # If no disclosure facts, set a high number    
        
        fact_df.loc[fact_df['fact_index'] >= min_disclosure_id_num, 'fact_included'] = False    
        fact_df.loc[fact_df['fact_index'] <= min_disclosure_id_num, 'fact_included'] = True    

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
    del t_pres, xid, tax, periods_dict
    try:
        gc.collect()
    except:
        pass
    return fact_df









# Add example usage function at the end of the file
if __name__ == "__main__":
    """Example of how to use the TaxonomyPresentation class with order information"""
    from openesef.edgar.loader import load_xbrl_filing
    #from openesef.engines.tax_pres import TaxonomyPresentation, ins_facts
    # Load a filing
    xid, tax = load_xbrl_filing(ticker="AAPL", year=2020)
    fact_df = ins_facts(xid, tax)

    #periods_dict = xid.identify_reporting_contexts()
    current_period_string = fact_df.period_string.value_counts().index[0]
    current_facts = fact_df[fact_df.period_string == current_period_string].reset_index(drop=True)
    
    t_pres = TaxonomyPresentation(tax)
    current_so_facts = current_facts.loc[current_facts.statement_name == t_pres.so_name].reset_index(drop=True)
    current_fp_facts = current_facts.loc[current_facts.statement_name == t_pres.fp_name].reset_index(drop=True)
    current_cf_facts = current_facts.loc[current_facts.statement_name == t_pres.cf_name].reset_index(drop=True)
    
    #print(current_so_facts[["fact_index", "label", "concept_name", "value_mln", "value", "fact_included"]])
    current_facts.loc[(current_facts['statement_name'] == 'CONSOLIDATEDSTATEMENTSOFOPERATIONS')  , ["fact_index", 'concept_name', "segment_axis", 'value', 'period_end', "fact_included"]].to_excel("/tmp/apple_2020_so.xlsx")
    #current_facts.iloc[64:155][["fact_index", 'concept_name', "segment_axis", 'value', 'period_end',"statement_name", "fact_included"]].to_excel("/tmp/apple_2020_so.xlsx")
    # Sort by order within statement
    #SalesRevenueAutomotive
    current_so_facts.iloc[4]
    fact_df.loc[fact_df.concept_name=="NetIncomeLoss"].to_excel("/tmp/ni.xlsx")
    fact_df.loc[fact_df.concept_name=="NetIncomeLoss"].reset_index(drop=True).iloc[0].to_dict()
    