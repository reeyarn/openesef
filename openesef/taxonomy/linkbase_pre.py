

from openesef.base import ebase, const #, util

from openesef.base import fbase, const, util
from openesef.taxonomy.locator import Locator
from openesef.util.util_mylogger import setup_logger #util_mylogger
import logging

if __name__=="__main__":
    logger = setup_logger("main", logging.DEBUG, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.taxonomy.linkbase_pre")

class PresentationArc(ebase.XmlElementBase):
    """
    Class representing a presentation arc in an XBRL linkbase.
    Extracts and stores the order attribute and other presentation-specific attributes.
    """
    def __init__(self, e, container_link=None):
        self.link = container_link
        super().__init__(e)
        
        # Extract common arc attributes
        self.from_label = e.attrib.get(f'{{{const.NS_XLINK}}}from')
        self.to_label = e.attrib.get(f'{{{const.NS_XLINK}}}to')
        self.arcrole = e.attrib.get(f'{{{const.NS_XLINK}}}arcrole')
        self.type = e.attrib.get(f'{{{const.NS_XLINK}}}type')
        
        # Extract presentation-specific attributes
        self.order = float(e.attrib.get('order', '0'))  # Default to 0 if not present
        self.priority = int(e.attrib.get('priority', '0'))
        self.use = e.attrib.get('use')
        self.preferred_label = e.attrib.get('preferredLabel')
        
        # Add to container link if provided
        if self.link is not None and hasattr(self.link, 'arcs'):
            self.link.arcs.append(self)

class PresentationLink(ebase.XmlElementBase):
    """
    Class representing a presentation link in an XBRL linkbase.
    Contains presentation arcs and manages their relationships.
    """
    def __init__(self, e, container_linkbase=None):
        self.linkbase = container_linkbase
        super().__init__(e)
        
        # Extract link attributes
        self.role = e.attrib.get(f'{{{const.NS_XLINK}}}role')
        self.type = e.attrib.get(f'{{{const.NS_XLINK}}}type')
        
        # Initialize collections
        self.locators = {}
        self.locators_by_href = {}
        self.arcs = []
        
        # Add to container linkbase if provided
        if self.linkbase is not None and hasattr(self.linkbase, 'links'):
            self.linkbase.links.append(self)


class PresentationLinkbase(fbase.XmlFileBase):
    """
    Class for handling XBRL presentation linkbases.
    Extends XmlFileBase to parse presentation links and arcs.
    """
    def __init__(self, location, container_pool, root=None, esef_filing_root=None, memfs=None):
        parsers = {
            f'{{{const.NS_LINK}}}linkbase': self.l_linkbase,
            f'{{{const.NS_LINK}}}presentationLink': self.l_presentation_link,
            f'{{{const.NS_LINK}}}loc': self.l_loc,
            f'{{{const.NS_LINK}}}presentationArc': self.l_presentation_arc,
            f'{{{const.NS_LINK}}}roleRef': self.l_role_ref,
            f'{{{const.NS_LINK}}}arcroleRef': self.l_arcrole_ref
        }
        
        self.location = location
        self.role_refs = {}
        self.arcrole_refs = {}
        self.refs = set()
        self.pool = container_pool
        self.memfs = memfs
        self.links = []
        self.current_link = None
        self.presentation_arcs = []
        
        resolved_location = util.reduce_url(location)
        if self.pool is not None:
            self.pool.discovered[location] = True
        
        try:
            super().__init__(location=resolved_location, container_pool=container_pool, 
                         parsers=parsers, root=root, esef_filing_root=esef_filing_root, memfs=memfs)
        except Exception as e:
            logger.error(f"Failed to load presentation linkbase: location={resolved_location}, "
                         f"esef_filing_root={esef_filing_root} \n{str(e)}")
    
    def l_linkbase(self, e):
        """Process linkbase elements"""
        return self
        
    def l_presentation_link(self, e):
        """Process presentation link elements"""
        link = PresentationLink(e, self)
        self.current_link = link
        return link
        
    def l_loc(self, e):
        """Process loc elements"""
        return Locator(e, self.current_link)
        
    def l_presentation_arc(self, e):
        """Process presentation arc elements"""
        arc = PresentationArc(e, self.current_link)
        self.presentation_arcs.append(arc)
        return arc
        
    def l_role_ref(self, e):
        """Process role ref elements"""
        role = e.attrib.get(f'{{{const.NS_XLINK}}}href')
        role_uri = e.attrib.get('roleURI')
        self.role_refs[role_uri] = role
        return None
        
    def l_arcrole_ref(self, e):
        """Process arcrole ref elements"""
        arcrole = e.attrib.get(f'{{{const.NS_XLINK}}}href')
        arcrole_uri = e.attrib.get('arcroleURI')
        self.arcrole_refs[arcrole_uri] = arcrole
        return None
    
    def get_presentation_hierarchy(self):
        """
        Returns a hierarchical structure of presentation relationships
        based on the order attribute.
        """
        hierarchy = {}
        
        # Group arcs by their parent (from_label)
        for arc in self.presentation_arcs:
            if arc.from_label not in hierarchy:
                hierarchy[arc.from_label] = []
            
            # Find the locator for the to_label
            to_locator = None
            if self.current_link and arc.to_label in self.current_link.locators:
                to_locator = self.current_link.locators[arc.to_label]
            
            hierarchy[arc.from_label].append({
                'to': arc.to_label,
                'order': arc.order,
                'priority': arc.priority,
                'preferred_label': arc.preferred_label,
                'locator': to_locator
            })
            
        # Sort children by order attribute
        for parent, children in hierarchy.items():
            children.sort(key=lambda x: x['order'])
            
        return hierarchy                        