"""
Taxonomy module for OpenESEF XBRL processing

This module provides the Taxonomy class which is responsible for loading, parsing, and providing 
access to XBRL taxonomy components including schemas, linkbases, concepts, and relationships.

## Update
Added presentation linkbase support that provides access to presentation hierarchies and order attributes.
This addition allows users to access the presentation order of concepts as defined in presentation arcs.

### Usage example:

#### Get all presentation linkbases

presentation_lbs = taxonomy.pres_linkbases
full_hierarchy = taxonomy.get_presentation_hierarchy()

terse_hierarchy = taxonomy.get_presentation_hierarchy(
    role="http://www.xbrl.org/2003/role/terseLabel"
)
#base.const.ROLE_LABEL_TERSE = 'http://www.xbrl.org/2003/role/terseLabel'

# Access order values from a specific linkbase
for plb in taxonomy.pres_linkbases:
    for arc in plb.presentation_arcs:
        print(f"From: {arc.from_label} -> To: {arc.to_label} | Order: {arc.order}")

        
#Get ordered concepts for a specific parent                
parent_concept = "us-gaap_StatementTable"
if parent_concept in full_hierarchy:
    ordered_children = full_hierarchy[parent_concept]
    for child in ordered_children:
        print(f"Child: {child['to']}, Order: {child['order']}")

                
"""

from openesef.base import const, data_wrappers, util
from openesef.taxonomy.xdt import dr_set
from openesef.taxonomy.label import LabelLinkbase
#from openesef.taxonomy.linkbase_pre import PresentationLinkbase  # Added this import for presentation linkbases on 20250304. 03:29 AM after arguing with devv.ai with claude 3.7
#from openesef.taxonomy.linkbase_pre import PresentationLinkbase

#from io import StringIO, BytesIO
import re

from openesef.util.util_mylogger import setup_logger #util_mylogger
import logging 
if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.taxonomy") 

import traceback


class Taxonomy:
    """ entry_points is a list of entry point locations
        cache_folder is the place where to store cached Web resources """
    def __init__(self, entry_points, container_pool, esef_filing_root = None, in_memory_content = {}, memfs=None):
        self.entry_points = entry_points
        self.pool = container_pool
        self.pool.current_taxonomy = self
        self.pool.current_taxonomy_hash = util.get_hash(','.join(entry_points)) if entry_points else None
        self.esef_filing_root = esef_filing_root  # Add ESEF location path
        self.in_memory_content = in_memory_content or {} # Dictionary to store in-memory content
        self.memfs = memfs
        # All schemas indexed by resolved location 
        self.schemas = {}
        # All linkbases indexed by resolved location 
        self.linkbases = {}
        self.processing_schemas = set()  # Track schemas being processed to prevent loops
        # All concepts  indexed by full id - target namespace + id 
        self.concepts = {}
        # All concepts indexed by QName
        self.concepts_by_qname = {}
        # General elements, which are not concepts 
        self.elements = {}
        self.elements_by_id = {}
        # All base set objects indexed by base set key 
        self.base_sets = {}
        # Dimension defaults - Key is dimension QName, value is default member concept 
        self.defaults = {}
        # Default Members - Key is the default member QName, value is the corresponding dimension concept. 
        self.default_members = {}
        # Dimensional Relationship Sets 
        self.dr_sets = {}
        # Excluding Dimensional Relationship Sets 
        self.dr_sets_excluding = {}
        # Key is primary item QName, value is the list of dimensional relationship sets, where it participates. 
        self.idx_pi_drs = {}
        # Key is the Qname of the dimensions. Value is the set of DR keys, where this dimension participates 
        self.idx_dim_drs = {}
        # Key is the QName of the hypercube. Value is the set of DR Keys, where this hypercube participates. 
        self.idx_hc_drs = {}
        # Key is the QName of the member. Value is the set of DR keys, where this member participates. 
        self.idx_mem_drs = {}
        # All table resources in taxonom 
        self.tables = {}
        # All role types in all schemas 
        self.role_types = {}
        self.role_types_by_href = {}
        # All arcrole types in all schemas 
        self.arcrole_types = {}
        self.arcrole_types_by_href = {}
        # Global resources - these, which have an id attribute 
        self.resources = {}
        # All locators 
        self.locators = {}
        # All parameters 
        self.parameters = {}
        # All assertions by type 
        self.value_assertions = {}
        self.existence_assertions = {}
        self.consistency_assertions = {}
        # Assertion Sets 
        self.assertion_sets = {}
        # Simple types 
        self.simple_types = {}
        # Complex types with simple content. Key is the QName, value is the item type object. 
        self.item_types = {}
        # Complex types with simple content. Key is the unique identifier, value is the item type object. 
        self.item_types_by_id = {}
        # Complex types with complex content: Key is qname, value is the tuple type object 
        self.tuple_types = {}
        # Complex types with complex content: Key is unique identifier, value is the tuple type object 
        self.tuple_types_by_id = {}
        if entry_points:
            self.load()
            self.compile()
            self.load_label_linkbases()
            self.load_presentation_linkbases()  # Added this line on 20250304. 03:29 AM after arguing with devv.ai with claude 3.7

    def __str__(self):
        return self.info()

    def __repr__(self):
        return self.info()

    def info(self):
        return '\n'.join([
            f'Schemas: {len(self.schemas)}',
            f'Linkbases: {len(self.linkbases)}',
            f'Role Types: {len(self.role_types)}',
            f'Arcrole Types: {len(self.arcrole_types)}',
            f'Concepts: {len(self.concepts)}',
            f'Item Types: {len(self.item_types)}',
            f'Tuple Types: {len(self.tuple_types)}',
            f'Simple Types: {len(self.simple_types)}',
            f'Labels: {sum([0 if not "label" in c.resources else len(c.resources["label"]) for c in self.concepts.values()])}',
            f'References: {sum([0 if not "reference" in c.resources else len(c.resources["reference"]) for c in self.concepts.values()])}',
            f'Hierarchies: {len(self.base_sets)}',
            f'Dimensional Relationship Sets: {len(self.base_sets)}',
            f'Dimensions: {len([c for c in self.concepts.values() if c.is_dimension])}',
            f'Hypercubes: {len([c for c in self.concepts.values() if c.is_hypercube])}',
            f'Enumerations: {len([c for c in self.concepts.values() if c.is_enumeration])}',
            f'Enumerations Sets: {len([c for c in self.concepts.values() if c.is_enumeration_set])}',
            f'Table Groups: {len([c for c in self.concepts.values() if "table" in c.resources])}',
            f'Tables: {len(self.tables)}',
            f'Parameters: {len(self.parameters)}',
            f'Assertion Sets: {len(self.assertion_sets)}',
            f'Value Assertions: {len(self.value_assertions)}',
            f'Existence Assertions: {len(self.existence_assertions)}',
            f'Consistency Assertions: {len(self.consistency_assertions)}'
        ])

    def _process_entry_point(self, entry_point):
        """Process a single entry point, tracking schema loading status"""
        if entry_point in self.processing_schemas:
            return  # Skip if already processing this schema
            
        self.processing_schemas.add(entry_point)
        try:
            # Load the schema
            #schema_obj = self.container_pool.add_schema(entry_point, self.esef_filing_root)
            schema_obj = self.pool.add_schema(location=entry_point, 
                                              esef_filing_root=self.esef_filing_root, 
                                              memfs=self.memfs)
            if schema_obj:
                self.schemas[entry_point] = schema_obj
        except Exception as e:
            logger.error(f'Taxonomy._process_entry_point(): Error processing {entry_point}: {e}')
            traceback.print_exc(limit=10)
        finally:
            self.processing_schemas.remove(entry_point)

    def load(self):
        for ep in self.entry_points:
            logger.debug(f'Taxonomy.load(): Loading {ep} with self.esef_filing_root={self.esef_filing_root}')
            logger.debug(f'Calling self.pool.add_reference(...) with href = {ep}, base = "", esef_filing_root = {self.esef_filing_root}')
            # Check if we have in-memory content
            if self.in_memory_content and ep in self.in_memory_content:
                logger.debug(f'Loading {ep} from memory')
                content = self.in_memory_content[ep]
                self.pool.add_reference_from_string(content, ep, '')
            else:
                logger.debug(f'Loading {ep} from file/URL')
                #self.pool.add_reference(href=ep, base='', esef_filing_root=self.esef_filing_root)

                self.pool.add_reference(href = ep, 
                                    base = '', 
                                    esef_filing_root = self.esef_filing_root,
                                    memfs = self.memfs)
            self._process_entry_point(ep)

    def add_in_memory_content(self, location, content):
        """Add content to be loaded from memory for a specific location"""
        self.in_memory_content[location] = content


    def resolve_prefix(self, pref):
        for sh in self.schemas.values():
            ns = sh.namespaces.get(pref, None)
            if ns is not None:
                return ns
        return None

    def resolve_qname(self, qname):
        pref = qname.split(':')[0] if ':' in qname else ''
        ns = self.resolve_prefix(pref)
        nm = qname.split(':')[1] if ':' in qname else qname
        return f'{ns}:{nm}'

    def attach_schema(self, href, sh):
        if href in self.schemas:
            return
        self.schemas[href] = sh
        for key, imp in sh.imports.items():
            logger.debug(f'Taxonomy.attach_schema(): Adding import {key} from {sh.base} with self.esef_filing_root={self.esef_filing_root}')
            logger.debug(f'Calling self.pool.add_reference(...) with href = {key}, base = {sh.base}, esef_filing_root = {self.esef_filing_root}')
            self.pool.add_reference(href = key, 
                                    base = sh.base, 
                                    esef_filing_root = self.esef_filing_root,
                                    memfs = self.memfs)
        for key, ref in sh.linkbase_refs.items():
            logger.debug(f'Taxonomy.attach_schema(): Adding linkbase {key} from {sh.base} with self.esef_filing_root={self.esef_filing_root}') 
            logger.debug(f'Calling self.pool.add_reference(...) with href = {key}, base = {sh.base}, esef_filing_root = {self.esef_filing_root}')
            self.pool.add_reference(href = key, 
                                    base = sh.base, 
                                    esef_filing_root = self.esef_filing_root,
                                    memfs = self.memfs)

    def attach_linkbase(self, href, lb):
        if href in self.linkbases:
            return
        self.linkbases[href] = lb
        for href in lb.refs:
            logger.debug(f'Taxonomy.attach_linkbase(): Adding reference {href} from {lb.base} with self.esef_filing_root={self.esef_filing_root}')
            logger.debug(f'Calling self.pool.add_reference(...) with href = {href}, base = {lb.base}, esef_filing_root = {self.esef_filing_root}')
            self.pool.add_reference(href = href, 
                                    base = lb.base, 
                                    esef_filing_root = self.esef_filing_root,
                                    memfs = self.memfs)

    def get_bs_roots(self, arc_name, role, arcrole):
        bs = self.base_sets.get(f'{arc_name}|{arcrole}|{role}')
        if not bs:
            return None
        return bs.roots

    def get_bs_members(self, arc_name, role, arcrole, start_concept=None, include_head=True):
        bs = self.base_sets.get(f'{arc_name}|{arcrole}|{role}', None)
        if not bs:
            return None
        return bs.get_members(start_concept, include_head)

    def get_enumerations(self):
        enumerations = {}
        for c in [c for k, c in self.concepts.items() if c.data_type and c.data_type.endswith('enumerationItemType')]:
            key = f'{c.linkrole}|{c.domain}|{c.head_usable}'
            e = enumerations.get(key)
            if not e:
                members = self.get_bs_members('definitionArc', c.linkrole, const.XDT_DOMAIN_MEMBER_ARCROLE, c.domain, c.head_usable)
                e = data_wrappers.Enumeration(key, [], [] if members is None else [m.Concept for m in members])
                enumerations[key] = e
            e.Concepts.append(c)
        return enumerations

    def get_enumeration_sets(self):
        enum_sets = {}
        for c in [c for k, c in self.concepts.items() if c.data_type and c.data_type.endswith('enumerationSetItemType')]:
            key = f'{c.linkrole}|{c.domain}|{c.head_usable}'
            e = enum_sets.get(key)
            if not e:
                members = self.get_bs_members('definitionArc', c.linkrole, const.XDT_DOMAIN_MEMBER_ARCROLE, c.domain, c.head_usable)
                if members is None:
                    continue
                e = data_wrappers.Enumeration(key, [], [m.Concept for m in members])
                enum_sets[key] = e
            e.Concepts.append(c)
        return enum_sets

    def compile(self):
        """Compile all taxonomy components"""
        self.compile_schemas()
        self.compile_linkbases()
        self.compile_defaults()
        self.compile_dr_sets()
        # Compile presentation networks after other compilations
        self.compile_presentation_networks()

    def compile_schemas(self):
        for sh in self.schemas.values():
            for c in sh.concepts.values():
                self.concepts_by_qname[c.qname] = c
                if c.id is not None:
                    key = f'{sh.location}#{c.id}'  # Key to search from locator href
                    self.concepts[key] = c
            for key, e in sh.elements.items():
                self.elements[key] = e
            for key, e in sh.elements_by_id.items():
                self.elements_by_id[key] = e
            for key, art in sh.arcrole_types.items():
                self.arcrole_types[key] = art
                self.arcrole_types_by_href[f'{sh.location}#{art.id}'] = art
            for key, rt in sh.role_types.items():
                self.role_types[key] = rt
                self.role_types_by_href[f'{sh.location}#{rt.id}'] = rt

            for key, it in sh.item_types.items():
                self.item_types[key] = it
            for key, it in sh.item_types_by_id.items():
                self.item_types_by_id[key] = it
            for key, tt in sh.tuple_types.items():
                self.tuple_types[key] = tt
            for key, tt in sh.tuple_types_by_id.items():
                self.tuple_types_by_id[key] = tt

            for key, st in sh.simple_types.items():
                self.simple_types[key] = st

    def compile_linkbases(self):
        logger.info(f"Starting compile_linkbases with {len(self.linkbases)} linkbases")
        
        # Pass 1 - Index global objects
        for href, lb in self.linkbases.items():
            logger.debug(f"Processing linkbase: {href} with {len(getattr(lb, 'links', []))} links")
            for xl in lb.links:
                logger.debug(f"  Link type: {xl.tag} with {len(xl.locators_by_href)} locators and {len(xl.resources)} resources")
                for key, loc in xl.locators_by_href.items():
                    self.locators[key] = loc
                for key, l_res in xl.resources.items():
                    for res in l_res:
                        if res.id:
                            href = f'{xl.linkbase.location}#{res.id}'
                            self.resources[href] = res
        
        logger.info(f"Indexed {len(self.locators)} locators and {len(self.resources)} resources")
        
        # # Pass 2 - Connect resources to each other
        # for href, lb in self.linkbases.items():
        #     logger.debug(f"Compiling linkbase: {href}")
        #     for xl in lb.links:
        #         xl.compile()

        # # Identify presentation linkbases
        # logger.info("Identifying presentation linkbases...")
        # self.presentation_linkbases = []
        # presentation_count = 0
        
        # for href, lb in self.linkbases.items():
        #     logger.debug(f"Checking linkbase: {href}")
        #     # Check if this is a presentation linkbase by looking at the file name or links
        #     is_presentation = False
        #     filename_match = '_pre.xml' in href.lower()
        #     links_match = False
            
        #     if hasattr(lb, 'links'):
        #         links_match = any(link.tag.endswith('presentationArc') for link in lb.links)  # Check for presentation arcs
            
        #     is_presentation = filename_match or links_match
        #     logger.debug(f"Linkbase {href}: filename_match={filename_match}, links_match={links_match}, is_presentation={is_presentation}")
            
        #     if is_presentation:
        #         try:
        #             from openesef.taxonomy.linkbase_pre import PresentationLinkbase
        #             logger.info(f"Creating PresentationLinkbase for {href}")
                    
        #             # Create a PresentationLinkbase object using the same location and pool
        #             pres_linkbase = PresentationLinkbase(
        #                 container_pool=self.pool,
        #                 location=href
        #             )
        #             pres_linkbase.location = href  # Ensure location is properly set
                    
        #             # Check if relationships were loaded
        #             relationship_count = sum(len(rels) for rels in pres_linkbase.relationships.values())
        #             logger.info(f"Loaded {relationship_count} presentation relationships from {href}")
                    
        #             # Add the presentation linkbase to the list
        #             self.presentation_linkbases.append(pres_linkbase)
        #             presentation_count += 1
                    
        #         except Exception as e:
        #             logger.warning(f"Error loading presentation linkbase {href}: {str(e)}")
        #             logger.debug(f"Exception details:", exc_info=True)
        
        # logger.info(f"Identified and loaded {presentation_count} presentation linkbases")

    def compile_defaults(self):
        # key = f'definitionArc|{const.XDT_DIMENSION_DEFAULT_ARCROLE}|{const.ROLE_LINK}'
        frag = f'definitionArc|{const.XDT_DIMENSION_DEFAULT_ARCROLE}'
        for key, bs in self.base_sets.items():
            if frag not in key:
                continue
            bs = self.base_sets.get(key, None)
        # if bs is None:
        #     return
            for dim in bs.roots:
                chain_dn = dim.chain_dn.get(key, None)
                if chain_dn is None:
                    continue
                for def_node in chain_dn:
                    self.defaults[dim.qname] = def_node.Concept.qname
                    self.default_members[def_node.Concept.qname] = dim.qname

    def compile_dr_sets(self):
        for bs in [bs for bs in self.base_sets.values() if bs.arc_name == 'definitionArc']:
            if bs.arcrole == const.XDT_DIMENSION_DEFAULT_ARCROLE:
                self.add_default_member(bs)
                continue
            if bs.arcrole == const.XDT_ALL_ARCROLE:
                self.add_drs(bs, self.dr_sets)
                continue
            if bs.arcrole == const.XDT_NOTALL_ARCROLE:
                self.add_drs(bs, self.dr_sets_excluding)
                continue

    def add_drs(self, bs, drs_collection):
        drs = dr_set.DrSet(bs, self)
        drs.compile()
        drs_collection[bs.get_key()] = drs

    def add_default_member(self, bs):
        for d in bs.roots:
            members = bs.get_members(start_concept=d, include_head=False)
            if not members:
                continue
            for m in members:
                self.defaults[d.qname] = m
                self.default_members[m.qname] = d

    def get_prefixes(self):
        return set(c.prefix for c in self.concepts.values())

    def get_languages(self):
        return set([r.lang for k, r in self.resources.items() if r.name == 'label'])
    
    ## 20250304. 02:37 AM added by devv.ai with claude 3.7
    def load_label_linkbases(self):
        """
        Load all label linkbases in the taxonomy.
        Issue to be solved? It seems that the load_label_linkbases() method is a custom approach that bypasses the standard linkbase loading process. 
        """
        self.label_linkbases = []
        
        # Access through the pool's file dictionary
        if hasattr(self.pool, 'file_dict'):
            for file_key in list(self.pool.file_dict.keys()):
                if '_lab.xml' in file_key:
                    try:
                        logger.debug(f"Loading label linkbase: {file_key}")
                        label_linkbase = LabelLinkbase(
                            self.pool,  # Pass the pool reference
                            location=file_key
                        )
                        self.label_linkbases.append(label_linkbase)
                    except Exception as e:
                        logger.warning(f"Error loading label linkbase {file_key}: {str(e)}")
        
        logger.debug(f"Loaded {len(self.label_linkbases)} label linkbases")

    ## 20250304. 04:12 AM added by devv.ai with claude 3.7
    def load_presentation_linkbases(self):
        """
        Load all presentation linkbases in the taxonomy.
        """
        
        
        self.presentation_linkbases = []
        
        # Access through the pool's file dictionary
        if hasattr(self.pool, 'file_dict'):
            for file_key in list(self.pool.file_dict.keys()):
                if '_pre.xml' in file_key:
                    try:
                        logger.info(f"Loading presentation linkbase: {file_key}")
                        pres_linkbase = PresentationLinkbase(
                            self.pool,  # Pass the pool reference
                            location=file_key
                        )
                        self.presentation_linkbases.append(pres_linkbase)
                    except Exception as e:
                        logger.warning(f"Error loading presentation linkbase {file_key}: {str(e)}")
        
        logger.info(f"Loaded {len(self.presentation_linkbases)} presentation linkbases")

    def get_presentation_relationships(self, role):
        """
        Get all presentation relationships for a specific role from all presentation linkbases.
        
        Args:
            role: The role URI
        
        Returns:
            List of PresentationRelationship objects
        """
        if not hasattr(self, 'presentation_linkbases'):
            return []
        
        relationships = []
        for linkbase in self.presentation_linkbases:
            relationships.extend(linkbase.get_relationships_by_role(role))
        
        # Sort by order
        relationships.sort()
        return relationships

    def get_presentation_tree(self, role):
        """
        Build a hierarchical presentation tree for a specific role.
        
        Args:
            role: The role URI
            
        Returns:
            Dictionary representing the combined tree structure from all linkbases
        """
        if not hasattr(self, 'presentation_linkbases') or not self.presentation_linkbases:
            return {}
        
        # Just use the first linkbase for now (can be enhanced to merge multiple linkbases)
        return self.presentation_linkbases[0].build_presentation_tree(role)

    def get_presentation_roles(self):
        """
        Get all presentation roles defined in the taxonomy.
        
        Returns:
            List of role URIs
        """
        if not hasattr(self, 'presentation_linkbases'):
            return []
        
        roles = set()
        for linkbase in self.presentation_linkbases:
            roles.update(linkbase.relationships.keys())
        
        return sorted(list(roles))

    def compile_presentation_networks(self):
        """Compile presentation networks from linkbases"""
        logger.info("Compiling presentation networks...")
        
        presentation_networks = []
        for lb_location, lb in self.linkbases.items():
            if '_pre.xml' in lb_location.lower():
                logger.info(f"Processing presentation linkbase: {lb_location}")
                try:
                    for link in lb.links:
                        if 'presentation' in str(link.tag).lower():
                            # Get role and arcrole
                            role = getattr(link, 'role', '') or link.attrib.get(f'{{{const.NS_XLINK}}}role', '')
                            arcrole = getattr(link, 'arcrole', '') or link.attrib.get(f'{{{const.NS_XLINK}}}arcrole', '')
                            
                            # Create base set key
                            key = ('presentationArc', role, arcrole)
                            
                            # Process the link if not already in base_sets
                            if key not in self.base_sets:
                                # Process locators and arcs
                                if hasattr(link, 'process_locators'):
                                    link.process_locators()
                                if hasattr(link, 'process_arcs'):
                                    link.process_arcs()
                                
                                # Create relationships from locators and arcs
                                relationships = []
                                if hasattr(link, 'locators') and hasattr(link, 'arcs'):
                                    concepts_by_label = {}
                                    
                                    # Map locator labels to concepts
                                    for loc in link.locators:
                                        if hasattr(loc, 'label') and hasattr(loc, 'href'):
                                            concept = self.get_concept_by_href(loc.href)
                                            if concept:
                                                concepts_by_label[loc.label] = concept
                                    
                                    # Create relationships from arcs
                                    for arc in link.arcs:
                                        if hasattr(arc, 'from_') and hasattr(arc, 'to'):
                                            from_concept = concepts_by_label.get(arc.from_)
                                            to_concept = concepts_by_label.get(arc.to)
                                            if from_concept and to_concept:
                                                rel = type('Relationship', (), {
                                                    'source': from_concept,
                                                    'target': to_concept,
                                                    'order': getattr(arc, 'order', None),
                                                    'preferred_label': getattr(arc, 'preferred_label', None)
                                                })
                                                relationships.append(rel)
                                
                                # Store the relationships with the link
                                link.relationships = relationships
                                self.base_sets[key] = link
                                presentation_networks.append(link)
                                
                                logger.debug(f"Added presentation link with {len(relationships)} relationships")
                                
                except Exception as e:
                    logger.warning(f"Error processing linkbase {lb_location}: {str(e)}")
                    logger.debug("Exception details:", exc_info=True)
                
        logger.info(f"Compiled {len(presentation_networks)} presentation networks")
        return presentation_networks

    def get_relationships(self, role=None, arcrole=None):
        """
        Get relationships from base sets matching the given role and arcrole.
        
        Args:
            role: The role URI to match
            arcrole: The arcrole URI to match
            
        Returns:
            List of relationship objects
        """
        relationships = []
        
        # Try to find matching base sets
        for key, base_set in self.base_sets.items():
            if not isinstance(key, tuple) or len(key) < 3:
                continue
            
            arc_name, bs_role, bs_arcrole = key
            
            # Check if this base set matches our criteria
            if 'presentation' in str(arc_name).lower():
                if (role is None or role == bs_role) and (arcrole is None or arcrole == bs_arcrole):
                    # Try different ways to get relationships from the base set
                    if hasattr(base_set, 'relationships'):
                        relationships.extend(base_set.relationships)
                    elif hasattr(base_set, 'arcs'):
                        # Convert arcs to relationships
                        for arc in base_set.arcs:
                            if hasattr(arc, 'from_') and hasattr(arc, 'to'):
                                # Try to find the concepts for from_ and to
                                from_concept = None
                                to_concept = None
                                
                                # Try to find concepts through locators
                                if hasattr(base_set, 'locators'):
                                    for loc in base_set.locators:
                                        if loc.label == arc.from_:
                                            from_concept = self.get_concept_by_href(loc.href)
                                        if loc.label == arc.to:
                                            to_concept = self.get_concept_by_href(loc.href)
                                
                                if from_concept and to_concept:
                                    # Create a relationship object
                                    rel = type('Relationship', (), {
                                        'source': from_concept,
                                        'target': to_concept,
                                        'order': getattr(arc, 'order', None),
                                        'preferred_label': getattr(arc, 'preferred_label', None)
                                    })
                                    relationships.append(rel)
        
        return relationships

    def get_concept_by_href(self, href):
        """
        Get a concept by its href reference.
        
        Args:
            href: The href string (e.g., "some_schema.xsd#concept_id")
            
        Returns:
            The concept object or None if not found
        """
        if re.search("mem:/\w", href):
            href = href.replace("mem:/", "mem://")
        if '#' in href:
            # Split the href into schema location and id
            schema_loc, concept_id = href.split('#')
            
            # Try to get the concept directly from concepts dictionary
            concept_key = f"{schema_loc}#{concept_id}"
            if concept_key in self.concepts:
                return self.concepts[concept_key]
            
            # If not found, try to find it in the schemas
            for schema in self.schemas.values():
                if concept_id in schema.concepts:
                    return schema.concepts[concept_id]
        
        return None