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
from openesef.taxonomy.label import Label
#from openesef.taxonomy.linkbase_pre import PresentationLinkbase  # Added this import for presentation linkbases on 20250304. 03:29 AM after arguing with devv.ai with claude 3.7
#from openesef.taxonomy.linkbase_pre import PresentationLinkbase
from openesef.taxonomy.xlink import XLink


#from io import StringIO, BytesIO
import re

from openesef.util.util_mylogger import setup_logger #util_mylogger
import logging 
if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.taxonomy") 

import traceback
from collections import defaultdict

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
        self.resources = []
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
            # Get label linkbase locations from linkbases
            label_locations = [loc for loc, lb in self.linkbases.items() 
                             if '_lab.xml' in loc.lower()]
            self.load_label_linkbases(label_locations)
        # Test label retrieval for revenue concepts
        if False: #testing code 
            for href, concept in self.concepts.items():
                #href = re.sub(r'mem:\/\/?', '', href)
                if "SalesRevenueAutomotive" in href or "SalesRevenueAutomotive" in str(concept.qname):
                    logger.info(f"\nTesting labels for concept: {href} {concept.qname}")
                    if hasattr(concept, 'get_label'):
                        # Try different roles and languages
                        roles = [
                            'http://www.xbrl.org/2003/role/label',
                            'http://www.xbrl.org/2003/role/terseLabel'
                        ]
                        languages = ['en', 'en-US']
                        
                        for role in roles:
                            for lang in languages:
                                label = concept.get_label(role=role, lang=lang)
                                logger.info(f"Label for role={role}, lang={lang}: {label}")
                        
                        # Also log the available roles and languages for this concept
                        if hasattr(concept, 'labels'):
                            logger.info(f"All available roles: {list(concept.labels.keys())}")
                            for role in concept.labels:
                                logger.info(f"Languages for role {role}: {list(concept.labels[role].keys())}")

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
            # f'Enumerations: {len([c for c in self.concepts.values() if c.is_enumeration])}',
            # f'Enumerations Sets: {len([c for c in self.concepts.values() if c.is_enumeration_set])}',
            # f'Table Groups: {len([c for c in self.concepts.values() if "table" in c.resources])}',
            # f'Tables: {len(self.tables)}',
            # f'Parameters: {len(self.parameters)}',
            # f'Assertion Sets: {len(self.assertion_sets)}',
            # f'Value Assertions: {len(self.value_assertions)}',
            # f'Existence Assertions: {len(self.existence_assertions)}',
            # f'Consistency Assertions: {len(self.consistency_assertions)}'
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
            #logger.debug(f'Taxonomy.load(): Loading {ep} with self.esef_filing_root={self.esef_filing_root}')
            #logger.debug(f'Calling self.pool.add_reference(...) with href = {ep}, base = "", esef_filing_root = {self.esef_filing_root}')
            # Check if we have in-memory content
            if self.in_memory_content and ep in self.in_memory_content:
                #logger.debug(f'Loading {ep} from memory')
                content = self.in_memory_content[ep]
                self.pool.add_reference_from_string(content, ep, '')
            else:
                #logger.debug(f'Loading {ep} from file/URL')
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
            #logger.debug(f'Taxonomy.attach_schema(): Adding import {key} from {sh.base} with self.esef_filing_root={self.esef_filing_root}')
            #logger.debug(f'Calling self.pool.add_reference(...) with href = {key}, base = {sh.base}, esef_filing_root = {self.esef_filing_root}')
            self.pool.add_reference(href = key, 
                                    base = sh.base, 
                                    esef_filing_root = self.esef_filing_root,
                                    memfs = self.memfs)
        for key, ref in sh.linkbase_refs.items():
            #logger.debug(f'Taxonomy.attach_schema(): Adding linkbase {key} from {sh.base} with self.esef_filing_root={self.esef_filing_root}') 
            #logger.debug(f'Calling self.pool.add_reference(...) with href = {key}, base = {sh.base}, esef_filing_root = {self.esef_filing_root}')
            self.pool.add_reference(href = key, 
                                    base = sh.base, 
                                    esef_filing_root = self.esef_filing_root,
                                    memfs = self.memfs)

    def attach_linkbase(self, href, lb):
        if href in self.linkbases:
            return
        self.linkbases[href] = lb
        for href in lb.refs:
            #logger.debug(f'Taxonomy.attach_linkbase(): Adding reference {href} from {lb.base} with self.esef_filing_root={self.esef_filing_root}')
            #logger.debug(f'Calling self.pool.add_reference(...) with href = {href}, base = {lb.base}, esef_filing_root = {self.esef_filing_root}')
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
        # Compile presentation and calculation networks
        self.compile_presentation_networks()
        self.compile_calculation_networks()

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
                #logger.debug(f"  Link type: {xl.tag} with {len(xl.locators_by_href)} locators and {len(xl.resources)} resources")
                for key, loc in xl.locators_by_href.items():
                    self.locators[key] = loc
                for key, l_res in xl.resources.items():
                    for res in l_res:
                        if res.id:
                            href = f'{xl.linkbase.location}#{res.id}'
                            self.resources.append(res)
        
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
        return set([r.lang for r in self.resources if r.name == 'label'])
    
    ## 20250304. 02:37 AM added by devv.ai with claude 3.7
    def load_label_linkbases(self, locations):
        """Load label linkbases from given locations"""
        for location in locations:
            try:
                # Get the linkbase from already loaded linkbases
                lb = self.linkbases.get(location)
                if not lb:
                    logger.warning(f"Linkbase not found for location: {location}")
                    continue
                    
                logger.info(f"There are {len(lb.links)} links in the label linkbase")
                
                # Process each link in the linkbase
                for labellink in lb.links:
                    try:
                        # Log basic info
                        logger.info(f"Processing label link with role: {labellink.role}")
                        
                        # First collect all labels
                        label_resources = {}
                        for child in labellink.element.iterchildren():
                            if child.tag.endswith('label'):
                                label_id = child.get(f'{{{const.NS_XLINK}}}label')
                                if label_id:
                                    if label_id not in label_resources:
                                        label_resources[label_id] = []
                                    label_resources[label_id].append({
                                        'role': child.get(f'{{{const.NS_XLINK}}}role', ''),
                                        'lang': child.get('{http://www.w3.org/XML/1998/namespace}lang', ''),
                                        'text': child.text
                                    })
                        
                        logger.info(f"Found {len(label_resources)} label resources")
                        
                        # Then process locators to get concepts
                        concepts = {}
                        for child in labellink.element.iterchildren():
                            if child.tag.endswith('loc'):
                                loc_label = child.get(f'{{{const.NS_XLINK}}}label')
                                href = child.get(f'{{{const.NS_XLINK}}}href')
                                if re.search("^\w", href) and not re.search("^(http|file)", href):
                                    href = "mem://" + href
                                if loc_label and href:
                                    if "tsla" in href and "SalesRevenueAutomotive" in loc_label: 
                                        logger.info(f"Locator {loc_label} href: {href}")
                                    concept = self.get_concept_by_href(href)
                                    if concept:
                                        concepts[loc_label] = concept
                                        if "tsla" in href and "SalesRevenueAutomotive" in loc_label: 
                                            logger.info(f"Concept {concept.qname}")
                        # Finally process arcs to connect concepts with labels
                        for child in labellink.element.iterchildren():
                            if child.tag.endswith('labelArc'):
                                from_label = child.get(f'{{{const.NS_XLINK}}}from')
                                to_label = child.get(f'{{{const.NS_XLINK}}}to')
                                if "SalesRevenueAutomotive" in from_label+to_label:
                                    logger.info(f"LabelArc from: {from_label} to: {to_label}")
                                concept = concepts.get(from_label)
                                labels = label_resources.get(to_label)
                                if concept and labels:
                                    if not hasattr(concept, 'labels'):
                                        concept.labels = {}
                                    
                                    for label in labels:
                                        role = label['role']
                                        lang = label['lang']
                                        text = label['text']
                                        
                                        if role not in concept.labels:
                                            concept.labels[role] = {}
                                        if lang not in concept.labels[role]:
                                            concept.labels[role][lang] = []
                                        concept.labels[role][lang].append(text)
                                        
                                        if re.search("sales.?revenue.?automotive", concept.qname+text, flags=re.IGNORECASE):
                                            logger.debug(f"Added label '{text}' to concept {concept.qname}")
                    
                    except Exception as e:
                        logger.warning(f"Error processing label link: {str(e)}")
                        logger.debug("Exception details:", exc_info=True)
                        continue
                    
            except Exception as e:
                logger.warning(f"Error processing label linkbase {location}: {str(e)}")
                logger.debug("Exception details:", exc_info=True)

    def compile_presentation_networks(self):
        """Compile presentation networks from linkbases"""
        logger.info("Compiling presentation networks...")
        
        presentation_networks = []
        for lb_location, lb in self.linkbases.items():
            if '_pre.xml' in lb_location.lower():
                #break
                logger.info(f"Found presentation linkbase: {lb_location}")
                logger.info(f"Number of links: {len(lb.links)}")
                try:
                    for link in lb.links:
                        #logger.debug(f"Processing link type: {link.tag}")
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
                                
                                
                except Exception as e:
                    logger.warning(f"Error processing linkbase {lb_location}: {str(e)}")
                    logger.debug("Exception details:", exc_info=True)
                
        logger.info(f"Compiled {len(presentation_networks)} presentation networks")
        return presentation_networks

    def compile_calculation_networks(self):
        """Compile calculation networks from linkbases"""
        #logger.info("Compiling calculation networks...")
        
        for lb_location, lb in self.linkbases.items():
            if '_cal.xml' in lb_location.lower():
                logger.info(f"Processing calculation linkbase: {lb_location}")
                logger.info(f"Number of links in linkbase: {len(lb.links)}")
                
                try:
                    for link in lb.links:
                        if 'calculation' in str(link.tag).lower():
                            role = getattr(link, 'role', '') or link.attrib.get(f'{{{const.NS_XLINK}}}role', '')
                            arcrole = getattr(link, 'arcrole', '') or link.attrib.get(f'{{{const.NS_XLINK}}}arcrole', '')
                            #logger.info(f"Role: {role}")
                            #logger.info(f"Arcrole: {arcrole}")

                            # Debug link object before processing
                            # logger.info("\nLink object before processing:")
                            # logger.info(f"  Type: {type(link)}")
                            # logger.info(f"  Dir: {dir(link)}")
                            # logger.info(f"  Raw XML: {link.tag} {link.attrib}")
                            
                            # Make sure link is properly initialized
                            if not hasattr(link, 'locators'):
                                link.locators = []  # Keep as list to match XLink class
                            if not hasattr(link, 'arcs'):
                                link.arcs = []  # Keep as list to match XLink class
                                
                            # Process the raw XML to populate link attributes
                            for child in link.element:
                                #logger.info(f"Child: {child.tag}")
                                if 'loc' in child.tag.lower():
                                    # Process locator
                                    label = child.attrib.get(f'{{{const.NS_XLINK}}}label')
                                    href = child.attrib.get(f'{{{const.NS_XLINK}}}href')
                                    if label and href:
                                        locator = type('Locator', (), {
                                            'label': label,
                                            'href': href,
                                            'type': child.attrib.get(f'{{{const.NS_XLINK}}}type'),
                                            'role': child.attrib.get(f'{{{const.NS_XLINK}}}role'),
                                            'attrib': child.attrib
                                        })
                                        link.locators[label] = locator  # Use label as key
                                        #logger.info(f"Added locator: {label} -> {href}")
                                    
                                elif 'calculationArc' in child.tag:
                                    # Process calculation arc
                                    from_label = child.attrib.get(f'{{{const.NS_XLINK}}}from')
                                    to_label = child.attrib.get(f'{{{const.NS_XLINK}}}to')
                                    if from_label and to_label:
                                        #logger.info(f"CalculationArc from: {from_label} to: {to_label}")
                                        arc = type('Arc', (), {
                                            'from_': from_label,
                                            'to': to_label,
                                            'weight': float(child.attrib.get('weight', 1.0)),
                                            'order': child.attrib.get('order'),
                                            'attrib': child.attrib
                                        })
                                        link.arcs.append(arc)  # Append to list
                                        logger.debug(f"Added arc: {from_label} -> {to_label}")
                        
                            # Debug link object after processing
                            # logger.info("\nLink object after processing:")
                            # logger.info(f"  Locators: {len(link.locators)}")
                            # logger.info(f"  Arcs: {len(link.arcs)}")
                            
                            # Process locators to map labels to concepts
                            concepts_by_label = {}
                            for label, loc in link.locators.items():  # Iterate over dict
                                concept = self.get_concept_by_href(loc.href)
                                if concept:
                                    concepts_by_label[label] = concept
                                    logger.debug(f"Mapped locator {loc.label} to concept {concept.qname}")
                                # else:
                                #     logger.warning(f"Could not find concept for href: {loc.href}")
                            
                            # Process calculation arcs and store relationships
                            relationships = []
                            for arc in link.arcs:  # Iterate over dict values
                                from_concept = concepts_by_label.get(arc.from_)
                                to_concept = concepts_by_label.get(arc.to)
                                #logger.info(f"CalculationArc from: {from_concept} to: {to_concept}")
                                if from_concept and to_concept:
                                    weight = float(getattr(arc, 'weight', 1.0))
                                    order = getattr(arc, 'order', None)
                                    
                                    relationships.append({
                                        'from': from_concept,
                                        'to': to_concept,
                                        'weight': weight,
                                        'order': order
                                    })
                                
                            # Store relationships in the link object and add to base_sets
                            link.relationships = relationships
                            base_set_key = ('calculationArc', role, arcrole)
                            if base_set_key not in self.base_sets:
                                self.base_sets[base_set_key] = link
                                #logger.info(f"Added calculation link to base_sets with key: {base_set_key}")
                                
                except Exception as e:
                    logger.warning(f"Error processing calculation linkbase {lb_location}: {str(e)}")
                    logger.debug("Exception details:", exc_info=True)
        
        # Log summary of what was added
        calc_arcs = [(k, v) for k, v in self.base_sets.items() if k[0] == 'calculationArc']
        #logger.info(f"Added {len(calc_arcs)} calculation networks to base_sets")
        # for key, link in calc_arcs:
        #     rel_count = len(getattr(link, 'relationships', []))
        #     logger.info(f"Role: {key[1]}")
        #     logger.info(f"Number of relationships: {rel_count}")
        #     if rel_count > 0:
        #         logger.debug("Sample relationships:")
        #         for rel in link.relationships[:3]:  # Show first 3 relationships
        #             logger.debug(f"  {rel['from'].qname} -> {rel['to'].qname} (weight: {rel['weight']})")

    def get_calculation_hierarchy(self, role=None):
        """
        Get the calculation hierarchy for a specific role or all roles.
        
        Args:
            role (str, optional): The role URI to filter by. If None, returns all roles.
            
        Returns:
            dict: Hierarchical structure of calculations where keys are parent concepts
                  and values are lists of child items with weights and orders.
        """
        hierarchy = {}
        
        # Find calculation arcs in base_sets using tuple key format
        for key, link in self.base_sets.items():
            if not isinstance(key, tuple) or len(key) != 3:
                continue
            
            arc_name, link_role, arcrole = key
            if arc_name == 'calculationArc' and (role is None or role == link_role):
                # Get relationships from the link
                if hasattr(link, 'relationships'):
                    for rel in link.relationships:
                        parent_qname = rel['from'].qname
                        if parent_qname not in hierarchy:
                            hierarchy[parent_qname] = []
                        
                        hierarchy[parent_qname].append({
                            'concept': rel['to'].qname,
                            'weight': rel['weight'],
                            'order': rel['order']
                        })
        
        # Sort children by order
        for parent in hierarchy:
            hierarchy[parent] = sorted(hierarchy[parent],
                                     key=lambda x: float(x['order']) if x['order'] is not None else float('inf'))
        
        
        
        return hierarchy

    def get_summation_items(self, total_concept, role=None):
        """
        Get all summation items that contribute to a total concept.
        
        Args:
            total_concept (str): The QName of the total concept
            role (str, optional): The specific role to look in
            
        Returns:
            list: List of dictionaries containing contributing items with weights
        """
        items = []
        
        # Find calculation arcs in base_sets using tuple key format
        for key, link in self.base_sets.items():
            if not isinstance(key, tuple) or len(key) != 3:
                continue
            
            arc_name, link_role, arcrole = key
            if arc_name == 'calculationArc' and (role is None or role == link_role):
                if hasattr(link, 'relationships'):
                    for rel in link.relationships:
                        if rel['from'].qname == total_concept:
                            items.append({
                                'concept': rel['to'].qname,
                                'weight': rel['weight'],
                                'order': rel['order']
                            })
        
        return sorted(items, key=lambda x: float(x['order']) if x['order'] is not None else float('inf'))
    
    

    def get_concept_by_href(self, href):
        """Get a concept by its href reference."""
        #logger.debug(f"Looking up concept by href: {href}")
        if re.search("mem:/\w", href):
            href = href.replace("mem:/", "mem://")
        if '#' in href:
            # Split the href into schema location and id
            schema_loc, concept_id = href.split('#')
            
            # Try to get the concept directly from concepts dictionary
            concept_key = f"{schema_loc}#{concept_id}"
            #logger.debug(f"Looking up concept with key: {concept_key}")
            if concept_key in self.concepts:
                concept = self.concepts[concept_key]
                # Add more detailed debugging for concept attributes
                #logger.debug(f"Found concept {concept.qname}:")
                #logger.debug(f"  - ID: {id(concept)}")
                #logger.debug(f"  - Labels: {getattr(concept, 'labels', {})}")
                #logger.debug(f"  - Name: {concept.name}")
                #logger.debug(f"  - Type: {concept.data_type}")
                return concept
            
            # If concept not found, log available concepts
            #logger.debug(f"Concept not found. Available concepts: {list(self.concepts.keys())[:5]}...")
            #logger.debug(f"Total number of concepts: {len(self.concepts)}")
        
        return None

    def get_calculation_hierarchy_dup(self, role=None):
        """
        Get the calculation hierarchy for a specific role or all roles if None.
        
        Args:
            role (str): The role URI to filter by (e.g., 'http://www.apple.com/role/CONSOLIDATEDSTATEMENTSOFCASHFLOWS')
        
        Returns:
            dict: Hierarchy where keys are parent concepts (totals) and values are lists of child items with weights and orders
        """
        hierarchy = {}
        
        for calc_lb in self.calculation_linkbases:
            #calc_lb = self.calculation_linkbases[0]
            for calc_role, relationships in calc_lb.relationships.items():
                if role is None or role == calc_role:
                    for rel in relationships:
                        parent_qname = rel['source'].qname
                        if parent_qname not in hierarchy:
                            hierarchy[parent_qname] = []
                        hierarchy[parent_qname].append({
                            'concept': rel['target'].qname,
                            'order': rel['order'],
                            'weight': rel['weight']
                        })
        
        # Sort children by order if specified
        for parent in hierarchy:
            hierarchy[parent] = sorted(hierarchy[parent], key=lambda x: float(x['order']) if x['order'] is not None else float('inf'))
        
        return hierarchy    