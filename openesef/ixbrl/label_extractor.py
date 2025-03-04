

"""
Module for extracting concept labels from XBRL label linkbases.
#added by devv.ai (not yet used by any module yet)
The code looks so broken.
"""

from lxml import etree
from collections import defaultdict


class XBRLLabelExtractor:
    """
    Class to extract concept labels from XBRL label linkbases
    """
    
    NS_MAP = {
        'link': 'http://www.xbrl.org/2003/linkbase',
        'xlink': 'http://www.w3.org/1999/xlink',
        'xml': 'http://www.w3.org/XML/1998/namespace'
    }
    
    def __init__(self, file_path=None, xml_content=None):
        """
        Initialize with either a file path or XML content
        
        :param file_path: Path to the XBRL label linkbase file
        :param xml_content: XML content as string
        """
        self.file_path = file_path
        self.xml_content = xml_content
        self.tree = None
        self.root = None
        self.concept_labels = defaultdict(dict)
        
        # Load and parse the XML
        self._load_xml()
        
        # Extract the labels
        self._extract_labels()
    
    def _load_xml(self):
        """Load and parse the XML file or content"""
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            
            if self.file_path:
                self.tree = etree.parse(self.file_path, parser=parser)
            elif self.xml_content:
                self.tree = etree.fromstring(self.xml_content, parser=parser).getroottree()
            else:
                raise ValueError("Either file_path or xml_content must be provided")
                
            self.root = self.tree.getroot()
        except Exception as e:
            raise ValueError(f"Error loading XBRL file: {str(e)}")
    
    def _extract_labels(self):
        """Extract concept labels from the XBRL file"""
        
        # Extract locators (concepts)
        locators = {}
        for loc in self.root.xpath('//link:loc', namespaces=self.NS_MAP):
            href = loc.attrib[f'{{{self.NS_MAP["xlink"]}}}href']
            label = loc.attrib[f'{{{self.NS_MAP["xlink"]}}}label']
            
            # Extract concept name from the href
            concept_name = href.split('#')[-1]
            locators[label] = concept_name
        
        # Extract labels
        labels = {}
        for label_elem in self.root.xpath('//link:label', namespaces=self.NS_MAP):
            label_id = label_elem.attrib[f'{{{self.NS_MAP["xlink"]}}}label']
            role = label_elem.attrib[f'{{{self.NS_MAP["xlink"]}}}role']
            text = label_elem.text
            lang = label_elem.attrib.get(f'{{{self.NS_MAP["xml"]}}}lang', 'en')
            
            labels[label_id] = {
                'role': role,
                'text': text,
                'lang': lang
            }
        
        # Extract arcs (relationships)
        for arc in self.root.xpath('//link:labelArc', namespaces=self.NS_MAP):
            from_label = arc.attrib[f'{{{self.NS_MAP["xlink"]}}}from']
            to_label = arc.attrib[f'{{{self.NS_MAP["xlink"]}}}to']
            
            if from_label in locators and to_label in labels:
                concept = locators[from_label]
                label_info = labels[to_label]
                
                # Extract role name for easier reference
                role_name = label_info['role'].split('/')[-1]
                
                # Store label by role
                self.concept_labels[concept][role_name] = {
                    'text': label_info['text'],
                    'lang': label_info['lang'],
                    'role': label_info['role']
                }
    
    def get_labels(self, concept=None):
        """
        Get labels for a specific concept or all concepts
        
        :param concept: Concept name (optional)
        :return: Dictionary of labels for the specified concept or all concepts
        """
        if concept:
            return self.concept_labels.get(concept, {})
        return dict(self.concept_labels)
    
    def get_label_text(self, concept, role='label'):
        """
        Get label text for a specific concept and role
        
        :param concept: Concept name
        :param role: Label role (default is standard label)
        :return: Label text or None if not found
        """
        labels = self.get_labels(concept)
        if labels and role in labels:
            return labels[role]['text']
        return None
    
if __name__ == "__main__":
    # Get all concept labels
    import requests 
    url = "https://www.sec.gov/Archives/edgar/data/1318605/000156459020004475/tsla-20191231_lab.xml"
    response = requests.get(url)
    with open('/tmp/tsla-20191231_lab.xml', 'wb') as file:
        file.write(response.content)
    label_extractor = XBRLLabelExtractor('/tmp/tsla-20191231_lab.xml')
    all_labels = label_extractor.get_labels()

    # Get labels for a specific concept
    concept = 'us-gaap_OperatingLeasesIncomeStatementLeaseRevenue'
    concept_labels = label_extractor.get_labels(concept)

    # Get the terse label text
    terse_label = label_extractor.get_label_text(concept, 'terseLabel')
    print(f"Concept: {concept}")
    print(f"Terse label: {terse_label}")  # Output: "Automotive leasing"    le = XBRLLabelExtractor(file_path="/Users/santhoshkumar/Downloads/us-gaap-2024-01-31.xml")
