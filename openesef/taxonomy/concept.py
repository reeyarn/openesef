from openesef.base import const, element, util
from openesef.taxonomy.label import Label, LabelLinkbase
from lxml import etree

from openesef.util.util_mylogger import setup_logger #util_mylogger
import logging 
if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.taxonomy.concept") 


class Concept(element.Element):
    def __init__(self, e, container_schema):
        super().__init__(e, container_schema)
        # Basic properties
        self.period_type = e.attrib.get(f'{{{const.NS_XBRLI}}}periodType')
        self.balance = e.attrib.get(f'{{{const.NS_XBRLI}}}balance')
        self.data_type = e.attrib.get('type')
        # Extensible enumerations properties
        domain = e.attrib.get(f'{{{const.NS_EXTENSIBLE_ENUMERATIONS}}}domain')
        domain2 = e.attrib.get(f'{{{const.NS_EXTENSIBLE_ENUMERATIONS_2}}}domain')
        self.domain = domain if domain is not None else domain2
        linkrole = e.attrib.get(f'{{{const.NS_EXTENSIBLE_ENUMERATIONS}}}linkrole')
        linkrole2 = e.attrib.get(f'{{{const.NS_EXTENSIBLE_ENUMERATIONS_2}}}linkrole')
        self.linkrole = linkrole if linkrole is not None else linkrole2
        hu = e.attrib.get(f'{{{const.NS_EXTENSIBLE_ENUMERATIONS}}}headUsable')
        hu2 = e.attrib.get(f'{{{const.NS_EXTENSIBLE_ENUMERATIONS_2}}}headUsable')
        self.head_usable = hu is not None and (hu.lower() == 'true' or hu == '1') or \
            hu2 is not None and (hu2.lower() == 'true' or hu == '1')
        # XDT specific properties
        self.typed_domain_ref = e.attrib.get(f'{{{const.NS_XBRLDT}}}typedDomainRef')
        self.is_dimension = self.substitution_group.endswith('dimensionItem')
        self.is_hypercube = self.substitution_group.endswith('hypercubeItem')
        self.is_explicit_dimension = True if self.is_dimension and self.typed_domain_ref is None else False
        self.is_typed_dimension = True if self.is_dimension and self.typed_domain_ref is not None else False
        self.is_enumeration = True if self.data_type and self.data_type.endswith('enumerationItemType') else False
        self.is_enumeration_set = True if self.data_type and self.data_type.endswith('enumerationSetItemType') else False

        if self.schema is not None:
            self.namespace = self.schema.target_namespace
        # Collections
        self.resources = {}  # Related labels - first by lang and then by role
        self.references = {}  # Related reference resources
        self.chain_up = {}  # Related parent concepts. Key is the base set key, value is the list of parent concepts
        self.chain_dn = {}  # Related child concepts. Key is the base set key, value is the list of child concepts

        unique_id = f'{self.namespace}:{self.name}'
        self.schema.concepts[unique_id] = self

        # Initialize labels
        self.labels = {}  # This will hold the labels for the concept
        self.element = e

    def __str__(self):
        return self.qname

    def __repr__(self):
        return self.qname

    def get_label(self, role=None, lang=None):
        """Get label for this concept with optional role and language"""
        if not hasattr(self, 'labels'):
            logger.debug(f"Concept {self.qname} has no labels attribute")
            return 'N/A'
        
        # If no role specified, try terse label first, then standard label
        if not role:
            common_roles = [
                'http://www.xbrl.org/2003/role/terseLabel',  # Try terse label first
                'http://www.xbrl.org/2003/role/label'
            ]
            for r in common_roles:
                if r in self.labels:
                    role = r
                    break
        
        # If still no role found, take first available
        if not role and self.labels:
            role = next(iter(self.labels.keys()))
            
        # Get labels for role
        role_labels = self.labels.get(role, {})
        if not role_labels:
            return 'N/A'
            
        # Map language codes
        lang_map = {
            'en': ['en', 'en-US', 'en-GB'],
            'en-US': ['en-US', 'en', 'en-GB'],
            'en-GB': ['en-GB', 'en', 'en-US']
        }
        
        # Try all language variants
        if lang in lang_map:
            for lang_variant in lang_map[lang]:
                if lang_variant in role_labels:
                    labels = role_labels[lang_variant]
                    if labels:
                        return labels[0]
        
        # If no specific language requested, try all English variants
        if not lang:
            for lang_code in ['en-US', 'en', 'en-GB']:
                if lang_code in role_labels:
                    labels = role_labels[lang_code]
                    if labels:
                        return labels[0]
        
        # If still nothing found, take first available language
        if role_labels:
            first_lang = next(iter(role_labels.keys()))
            labels = role_labels[first_lang]
            if labels:
                return labels[0]
            
        logger.debug(f"No suitable label found for {self.qname} with role={role} and lang={lang}")
        return 'N/A'

    def get_label_or_qname(self, lang='en', role='/label'):
        lbl = util.get_label(self.resources, lang, role)
        return lbl if lbl else self.qname

    def get_label_or_name(self, lang='en', role='/label'):
        lbl = util.get_label(self.resources, lang, role)
        return self.name if lbl is None else lbl

    def get_lang(self):
        return util.get_lang(self.resources)

    def get_enum_label(self, role):
        labels = self.resources.get('label', None)
        if labels is None:
            return None
        candidates = [l for lbls in labels.values() for l in lbls if l.xlink.role == role]
        if not candidates:
            return util.get_label(self.resources)
        return candidates[0].text

    def get_reference(self, lang='en', role='/label'):
        return util.get_reference(self.resources, lang, role)

    def info(self):
        return '\n'.join([
            f'QName: {self.qname}',
            f'Data type: {self.data_type}',
            f'Abstract: {self.abstract}',
            f'Nillable: {self.nillable}',
            f'Period Type: {self.period_type}',
            f'Balance: {self.balance}'])
    
    # def get_label_by_devv(self, role='http://www.xbrl.org/2003/role/label', lang='en'):
    #     """
    #     Get the label for this concept.
        
    #     Args:
    #         role: The label role (default is standard label)
    #         lang: The language (default is English)
            
    #     Returns:
    #         The label text or the concept name if no label found
    #     """
    #     if hasattr(self, 'taxonomy') and self.taxonomy:
    #         return self.taxonomy.get_concept_label(self.name, role, lang)
        
    #     # If we have a QName attribute, try to use that
    #     if hasattr(self, 'qname'):
    #         qname_str = str(self.qname)
    #         if ':' in qname_str:
    #             concept_id = qname_str.split(':')[-1]
    #             if hasattr(self, 'taxonomy') and self.taxonomy:
    #                 return self.taxonomy.get_concept_label(concept_id, role, lang)
        
    #     # Fallback to name
    #     return self.name if hasattr(self, 'name') else str(self)