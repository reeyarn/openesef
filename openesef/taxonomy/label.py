"""
THIS MODULE IS NOT USED. TO BE DELETED.

<crossout>Module for handling XBRL label linkbases and concept labels.</crossout>

"""

from openesef.base import fbase
from lxml import etree as lxml_etree

from openesef.util.util_mylogger import setup_logger #util_mylogger
import logging 
if __name__=="__main__":
    logger = setup_logger("main", logging.INFO, log_dir="/tmp/log/")
else:
    logger = logging.getLogger("main.openesf.taxonomy.label") 


class Label:
    """
    Represents a label for a concept in an XBRL taxonomy.
    """
    def __init__(self, label_text, lang, role):
        self.label_text = label_text
        self.lang = lang
        self.role = role

    def __str__(self):
        return self.label_text


class LabelLinkbase(fbase.XmlFileBase):
    """
    Represents a label linkbase in an XBRL taxonomy.
    """
    def __init__(self, container_pool, location=None, root=None, memfs=None):
        super().__init__(container_pool, location, root, memfs)
        self.labels = {}  # Dictionary to store labels: {concept_id: {role: Label}}
        self.parse_labels()

    def parse_labels(self):
        """
        Parse the label linkbase to extract concept labels.
        """
        if self.root is None:
            logger.warning(f"No root element for {self.location}")
            return
        
        # Extract namespaces
        nsmap = self.root.nsmap
        
        # Define namespace prefixes
        link_ns = '{{{}}}'.format(nsmap.get('link', 'http://www.xbrl.org/2003/linkbase'))
        xlink_ns = '{{{}}}'.format(nsmap.get('xlink', 'http://www.w3.org/1999/xlink'))
        
        # Find all label elements
        label_elements = self.root.findall(f'.//{link_ns}label')
        
        # Dictionary to store labels by their xlink:label attribute
        labels_by_id = {}
        
        # Process label elements
        for label_elem in label_elements:
            label_id = label_elem.get(f'{xlink_ns}label')
            label_role = label_elem.get(f'{xlink_ns}role', 'http://www.xbrl.org/2003/role/label')
            label_lang = label_elem.get('{http://www.w3.org/XML/1998/namespace}lang', 'en')
            label_text = label_elem.text
            
            if label_id and label_text:
                if label_id not in labels_by_id:
                    labels_by_id[label_id] = {}
                labels_by_id[label_id][label_role] = Label(label_text, label_lang, label_role)
        
        # Find all labelArc elements
        label_arcs = self.root.findall(f'.//{link_ns}labelArc')
        
        # Process labelArc elements to connect concepts to their labels
        for arc in label_arcs:
            from_id = arc.get(f'{xlink_ns}from')
            to_id = arc.get(f'{xlink_ns}to')
            
            if from_id and to_id and to_id in labels_by_id:
                # Get the concept ID by removing any suffix after an underscore
                concept_id = from_id.split('_')[0]
                
                if concept_id not in self.labels:
                    self.labels[concept_id] = {}
                
                # Add all labels for this concept
                for role, label in labels_by_id[to_id].items():
                    self.labels[concept_id][role] = label
        
        logger.info(f"Parsed {len(self.labels)} concept labels from {self.location}")

    def get_label(self, concept_id, role='http://www.xbrl.org/2003/role/label', lang='en'):
        """
        Get a label for a concept.
        
        Args:
            concept_id: The concept ID
            role: The label role (default is standard label)
            lang: The language (default is English)
            
        Returns:
            The label text or None if not found
        """
        if concept_id in self.labels and role in self.labels[concept_id]:
            label = self.labels[concept_id][role]
            if label.lang.startswith(lang):
                return label.label_text
        
        # If preferred role not found, try terseLabel
        if role != 'http://www.xbrl.org/2003/role/terseLabel' and concept_id in self.labels:
            terse_role = 'http://www.xbrl.org/2003/role/terseLabel'
            if terse_role in self.labels[concept_id]:
                label = self.labels[concept_id][terse_role]
                if label.lang.startswith(lang):
                    return label.label_text
        
        # Fall back to any available label
        if concept_id in self.labels:
            for role, label in self.labels[concept_id].items():
                if label.lang.startswith(lang):
                    return label.label_text
        
        return None