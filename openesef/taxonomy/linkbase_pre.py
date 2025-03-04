"""
Module for handling XBRL presentation linkbases.
"""

from openesef.base import fbase
from lxml import etree as lxml_etree
from openesef.taxonomy.linkbase import Linkbase
import logging
from collections import defaultdict
from typing import Any
import traceback
#logger = logging.getLogger(__name__)
from openesef.util.util_mylogger import setup_logger
logger = setup_logger("test_linkbase", logging.DEBUG, log_dir="/tmp/", full_format=False)

class PresentationRelationship:
    """
    Represents a presentation relationship between two concepts in an XBRL taxonomy.
    """
    def __init__(self, parent, child, order, preferred_label=None, priority=None):
        self.parent = parent
        self.child = child
        self.order = float(order)
        self.preferred_label = preferred_label
        self.priority = int(priority) if priority else 0
        
    def __str__(self):
        return f"{self.parent} → {self.child} (order: {self.order})"
    
    def __lt__(self, other):
        return self.order < other.order



class PresentationLinkbase(Linkbase):
    """
    Represents a presentation linkbase in an XBRL taxonomy.
    """
    def __init__(self, location=None, container_pool=None, root=None, esef_filing_root=None, memfs=None):
        logger.info(f"Initializing PresentationLinkbase: location={location}, root={root is not None}, esef_filing_root={esef_filing_root}")
        try:
            # Load the XML using the superclass method
            
            
            self.role_refs = {}  # Dictionary to store role references
            self.relationships = defaultdict(list)  # Dictionary to store relationships by role
            self.esef_filing_root = esef_filing_root
            self.memfs = memfs
            self.root = root
            super().__init__(location, container_pool, root, esef_filing_root, memfs)
            logger.info(f"PresentationLinkbase initialized, parsing presentation linkbase...")
            
            self.parse_presentation_linkbase()
            logger.info(f"PresentationLinkbase parsing completed with {sum(len(rels) for rels in self.relationships.values())} total relationships")
        except Exception as e:
            logger.error(f"Error initializing PresentationLinkbase: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
            
    def __str__(self):
        return self.info()
    
    def __reduce__(self) -> str | tuple[Any, ...]:
        return self.__str__()
    
    def info(self):
        return f"PresentationLinkbase(location={self.location}, root={self.root is not None}, relationships={sum(len(rels) for rels in self.relationships.values())})"
    
    def parse_presentation_linkbase(self):
        """
        Parse the presentation linkbase to extract relationships and ordering.
        """
        logger.info(f"Starting parse_presentation_linkbase for {self.location}")
        
        if self.root is None:
            logger.warning(f"No root element for {self.location}, attempting to load from file")
            try:
                # Try to load the file if root is not provided
                if hasattr(self, 'xml_root') and self.xml_root is not None:
                    self.root = self.xml_root
                    logger.info(f"Using xml_root from parent class")
                else:
                    logger.warning(f"No xml_root available, cannot parse presentation linkbase")
                    return
            except Exception as e:
                logger.error(f"Failed to load root element: {str(e)}")
                return
        
        # Extract namespaces
        nsmap = self.root.nsmap
        logger.debug(f"Namespace map: {nsmap}")
        
        # Define namespace prefixes
        link_ns = '{{{}}}'.format(nsmap.get('link', 'http://www.xbrl.org/2003/linkbase'))
        xlink_ns = '{{{}}}'.format(nsmap.get('xlink', 'http://www.w3.org/1999/xlink'))
        logger.debug(f"Using link_ns={link_ns}, xlink_ns={xlink_ns}")
        
        # Parse roleRef elements
        role_refs = self.root.findall(f'.//{link_ns}roleRef')
        logger.debug(f"Found {len(role_refs)} roleRef elements")
        for role_ref in role_refs:
            role_uri = role_ref.get(f'{xlink_ns}href')
            role_id = role_ref.get('roleURI')
            self.role_refs[role_id] = role_uri
            logger.debug(f"Added roleRef: {role_id} -> {role_uri}")
        
        # Find all presentationLink elements
        pres_links = self.root.findall(f'.//{link_ns}presentationLink')
        logger.info(f"Found {len(pres_links)} presentationLink elements")
        
        for i, pres_link in enumerate(pres_links):
            role = pres_link.get(f'{xlink_ns}role')
            logger.debug(f"Processing presentationLink {i+1}/{len(pres_links)} with role: {role}")
            
            # Find all presentationArc elements in this link
            pres_arcs = pres_link.findall(f'.//{link_ns}presentationArc')
            logger.debug(f"Found {len(pres_arcs)} presentationArc elements in role {role}")
            
            for j, arc in enumerate(pres_arcs):
                from_id = arc.get(f'{xlink_ns}from')
                to_id = arc.get(f'{xlink_ns}to')
                order = arc.get('order')
                preferred_label = arc.get('preferredLabel')
                priority = arc.get('priority')
                
                if from_id and to_id and order:
                    relationship = PresentationRelationship(
                        parent=from_id,
                        child=to_id,
                        order=order,
                        preferred_label=preferred_label,
                        priority=priority
                    )
                    self.relationships[role].append(relationship)
                    logger.debug(f"Added relationship: {from_id} -> {to_id} (order: {order})")
                else:
                    logger.warning(f"Incomplete arc data: from={from_id}, to={to_id}, order={order}")
        
        # Sort relationships by order within each role
        for role in self.relationships:
            self.relationships[role].sort()
            logger.debug(f"Sorted {len(self.relationships[role])} relationships for role {role}")
        
        logger.info(f"Parsed {sum(len(rels) for rels in self.relationships.values())} presentation relationships from {self.location}")

    def get_relationships_by_role(self, role):
        """
        Get all presentation relationships for a specific role.
        
        Args:
            role: The role URI
            
        Returns:
            List of PresentationRelationship objects
        """
        relationships = self.relationships.get(role, [])
        logger.debug(f"Retrieved {len(relationships)} relationships for role {role}")
        return relationships
    
    def get_children(self, parent_id, role):
        """
        Get all children of a specific parent concept in a specific role.
        
        Args:
            parent_id: The parent concept ID
            role: The role URI
            
        Returns:
            List of (child_id, order, preferred_label) tuples, sorted by order
        """
        relationships = self.get_relationships_by_role(role)
        children = []
        
        for rel in relationships:
            if rel.parent == parent_id:
                children.append((rel.child, rel.order, rel.preferred_label))
        
        # Sort by order
        children.sort(key=lambda x: x[1])
        logger.debug(f"Found {len(children)} children for parent {parent_id} in role {role}")
        return children
    
    def get_parent(self, child_id, role):
        """
        Get the parent of a specific child concept in a specific role.
        
        Args:
            child_id: The child concept ID
            role: The role URI
            
        Returns:
            Tuple of (parent_id, order, preferred_label) or None if no parent found
        """
        relationships = self.get_relationships_by_role(role)
        
        for rel in relationships:
            if rel.child == child_id:
                logger.debug(f"Found parent {rel.parent} for child {child_id} in role {role}")
                return (rel.parent, rel.order, rel.preferred_label)
        
        logger.debug(f"No parent found for child {child_id} in role {role}")
        return None
    
    def build_presentation_tree(self, role):
        """
        Build a hierarchical presentation tree for a specific role.
        
        Args:
            role: The role URI
            
        Returns:
            Dictionary representing the tree structure
        """
        logger.info(f"Building presentation tree for role {role}")
        relationships = self.get_relationships_by_role(role)
        
        # Find root elements (those that are parents but not children)
        all_parents = set(rel.parent for rel in relationships)
        all_children = set(rel.child for rel in relationships)
        root_elements = all_parents - all_children
        logger.debug(f"Found {len(root_elements)} root elements for role {role}")
        
        # Build tree recursively
        tree = {}
        
        def add_children(parent_id):
            children = {}
            child_count = 0
            for rel in relationships:
                if rel.parent == parent_id:
                    children[rel.child] = {
                        'order': rel.order,
                        'preferred_label': rel.preferred_label,
                        'children': add_children(rel.child)
                    }
                    child_count += 1
            
            logger.debug(f"Added {child_count} children for parent {parent_id}")
            # Sort children by order
            return {k: children[k] for k in sorted(children, key=lambda x: children[x]['order'])}
        
        # Start with root elements
        for root in root_elements:
            logger.debug(f"Processing root element {root}")
            tree[root] = {
                'order': 0,  # Root elements don't have an explicit order
                'preferred_label': None,
                'children': add_children(root)
            }
        
        logger.info(f"Completed presentation tree for role {role} with {len(tree)} top-level elements")
        return tree

    def load_xml(self, location):
        """ Load the XML file and return the root element. """
        try:
            tree = lxml_etree.parse(location)
            return tree.getroot()
        except Exception as e:
            logger.error(f"Failed to load XML from {location}: {str(e)}")
            raise

    def get_order_for_concept(self, concept_qname):
        """Retrieve the order for a given concept QName."""
        logger.debug(f"Retrieving order for concept QName: {concept_qname}")
        for rels in self.relationships.values():
            for rel in rels:
                logger.debug(f"Checking relationship: {rel.child} with order {rel.order}")
                if rel.child == concept_qname:
                    return rel.order  # Assuming rel.order holds the order value
        return None

if __name__ == "__main__":
    from openesef.taxonomy.taxonomy import Taxonomy
    from openesef.base.pool import Pool
    from openesef.util.util_mylogger import setup_logger
    import os
    import logging

    logger = setup_logger("test_linkbase", logging.DEBUG, log_dir="/tmp/")
    data_pool = Pool(max_error=10)

    location_linkbase_pre = "./examples/tsla_2019_min/tsla-20191231_pre.xml"
    location_taxonomy = "./examples/tsla_2019_min/tsla-20191231.xsd"
    
    # Load taxonomy
    entry_points = [location_linkbase_pre, location_taxonomy]
    tax = data_pool.add_taxonomy(entry_points, esef_filing_root=os.getcwd() + "./examples/tsla_2019_min/")

    # Load presentation linkbase directly for further debugging
    linkbase_pre = PresentationLinkbase(container_pool=data_pool, location=location_linkbase_pre)
    logger.info(f"Loaded presentation linkbase directly: {linkbase_pre.location}")
    logger.info(f"Total relationships in the directly loaded linkbase: {sum(len(rels) for rels in linkbase_pre.relationships.values())}")   

    # Debugging: Check if the taxonomy has loaded the presentation linkbases
    if hasattr(tax, 'presentation_linkbases'):
        logger.info(f"Number of presentation linkbases loaded into taxonomy: {len(tax.presentation_linkbases)}")
        for pres_linkbase in tax.presentation_linkbases:
            logger.info(f"Loaded presentation linkbase: {pres_linkbase.location}")
            logger.info(f"Total relationships in this linkbase: {sum(len(rels) for rels in pres_linkbase.relationships.values())}")
    else:
        logger.warning("No presentation linkbases found in the taxonomy.")
    
