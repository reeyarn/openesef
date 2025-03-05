import sys
#sys.path.insert(0,  '../..')
from openesef.base.pool import Pool
import requests
import os
import pandas as pd
import logging
import xml.etree.ElementTree as ET
import re

from openesef.taxonomy.linkbase_pre import PresentationLinkbase
from openesef.engines import tax_reporter
from openesef.util.util_mylogger import setup_logger

# Set up logging
logger = setup_logger("test_linkbase", logging.DEBUG, log_dir="/tmp/", full_format=False)

# File locations
location_xbrl = './examples/tsla_2019_min/tsla-20191231_htm.xml'
location_taxonomy = './examples/tsla_2019_min/tsla-20191231.xsd'
location_linkbase_cal = './examples/tsla_2019_min/tsla-20191231_cal.xml'
location_linkbase_def = './examples/tsla_2019_min/tsla-20191231_def.xml'
location_linkbase_lab = './examples/tsla_2019_min/tsla-20191231_lab.xml'
location_linkbase_pre = './examples/tsla_2019_min/tsla-20191231_pre.xml'

# Initialize pool with cache
data_pool = Pool(max_error=10)

# Load taxonomy
entry_points = [location_linkbase_pre, location_taxonomy]
tax = data_pool.add_taxonomy(entry_points, esef_filing_root=os.getcwd()+"./examples/tsla_2019_min/")

# Load presentation linkbase
linkbase_pre = PresentationLinkbase(container_pool=data_pool, location=location_linkbase_pre)
print(f"Loaded presentation linkbase: {linkbase_pre}")

# Inspect the linkbase object to see available attributes and methods
print("\nInspecting PresentationLinkbase object:")
print(f"Attributes: {dir(linkbase_pre)}")

# Try to get roles from the taxonomy
print("\nTrying to get roles from taxonomy...")
roles = tax.get_presentation_roles() if hasattr(tax, 'get_presentation_roles') else []
print(f"Found {len(roles)} presentation roles from taxonomy")
for i, role in enumerate(roles):
    print(f"{i+1}. {role}")

# Try TaxonomyReporter for additional functionality
print("\nTrying TaxonomyReporter for additional insights...")
reporter = tax_reporter.TaxonomyReporter(tax)

# Based on parse_concepts.py, check for base_sets in the taxonomy
print("\nExamining base_sets in taxonomy:")
if hasattr(tax, 'base_sets'):
    print(f"Found {len(tax.base_sets)} base sets in taxonomy")
    
    # Find presentation networks
    presentation_networks = []
    for key, base_set in tax.base_sets.items():
        if 'presentation' in str(key).lower():
            print(f"\nFound presentation base set: {key}")
            presentation_networks.append(base_set)
    
    print(f"Found {len(presentation_networks)} presentation networks")

# Direct XML parsing to extract order information
print("\nDirectly parsing the presentation linkbase XML file:")
try:
    # Define namespaces
    namespaces = {
        'link': 'http://www.xbrl.org/2003/linkbase',
        'xlink': 'http://www.w3.org/1999/xlink'
    }
    
    # Parse the XML file
    tree = ET.parse(location_linkbase_pre)
    root = tree.getroot()
    
    # Find all presentation links (roles)
    presentation_links = root.findall('.//link:presentationLink', namespaces)
    print(f"Found {len(presentation_links)} presentation links (roles)")
    
    # For each presentation link, find the arcs and extract order information
    for i, link in enumerate(presentation_links[:2]):  # Limit to first 2 for brevity
        role = link.get('{http://www.w3.org/1999/xlink}role')
        print(f"\nRole {i+1}: {role}")
        
        # Find all presentation arcs
        arcs = link.findall('.//link:presentationArc', namespaces)
        print(f"  Found {len(arcs)} presentation arcs")
        
        # Extract information from the first few arcs
        arc_data = []
        for j, arc in enumerate(arcs[:5]):  # Show first 5
            from_label = arc.get('{http://www.w3.org/1999/xlink}from')
            to_label = arc.get('{http://www.w3.org/1999/xlink}to')
            order = arc.get('order')
            priority = arc.get('priority')
            preferred_label = arc.get('preferredLabel')
            
            print(f"  Arc {j+1}: From={from_label}, To={to_label}, Order={order}, Priority={priority}")
            
            arc_data.append({
                'from': from_label,
                'to': to_label,
                'order': float(order) if order else None,
                'priority': int(priority) if priority else None,
                'preferred_label': preferred_label
            })
        
        # Convert to DataFrame for easier analysis
        if arc_data:
            df = pd.DataFrame(arc_data)
            print("\n  Order statistics:")
            print(f"    Min: {df['order'].min()}")
            print(f"    Max: {df['order'].max()}")
            print(f"    Mean: {df['order'].mean():.2f}")
            print(f"    Unique values: {len(df['order'].unique())}")
            
            # Build a simple hierarchy based on order
            print("\n  Building hierarchy based on order:")
            # Group by 'from' and sort by order
            for from_label, group in df.groupby('from'):
                sorted_group = group.sort_values('order')
                print(f"    Parent: {from_label}")
                for _, row in sorted_group.iterrows():
                    print(f"      Child: {row['to']} (Order: {row['order']})")
                    
except Exception as e:
    print(f"Error parsing XML: {str(e)}")

# Examine the presentation linkbase in the taxonomy
print("\nExamining presentation linkbases in taxonomy:")
if hasattr(tax, 'presentation_linkbases'):
    print(f"Found {len(tax.presentation_linkbases)} presentation linkbases in taxonomy")
    
    # Check if our linkbase is in the taxonomy's presentation linkbases
    for i, plb in enumerate(tax.presentation_linkbases):
        print(f"Linkbase {i+1}: {plb.location}")
        
        # Check for presentation arcs with order
        if hasattr(plb, 'presentation_arcs'):
            print(f"  Found {len(plb.presentation_arcs)} presentation arcs")
            for j, arc in enumerate(plb.presentation_arcs[:5]):  # Show first 5
                order = arc.order if hasattr(arc, 'order') else None
                print(f"  Arc {j+1}: From={arc.from_label}, To={arc.to_label}, Order={order}")
else:
    print("No presentation_linkbases attribute found in taxonomy")
    
    # Since the taxonomy doesn't have presentation linkbases loaded properly,
    # let's try to manually add our parsed information to the linkbase_pre object
    print("\nAttempting to manually add presentation arcs to linkbase_pre object...")
    try:
        if not hasattr(linkbase_pre, 'presentation_arcs'):
            linkbase_pre.presentation_arcs = []
            
        # Parse the XML file again to add arcs
        tree = ET.parse(location_linkbase_pre)
        root = tree.getroot()
        
        # Find all presentation arcs
        all_arcs = root.findall('.//link:presentationArc', namespaces)
        print(f"Found {len(all_arcs)} presentation arcs in XML")
        
        # Create a simple class to hold arc information
        class PresentationArc:
            def __init__(self, from_label, to_label, order, priority, preferred_label):
                self.from_label = from_label
                self.to_label = to_label
                self.order = float(order) if order else None
                self.priority = int(priority) if priority else None
                self.preferred_label = preferred_label
        
        # Add arcs to the linkbase
        for arc in all_arcs:
            from_label = arc.get('{http://www.w3.org/1999/xlink}from')
            to_label = arc.get('{http://www.w3.org/1999/xlink}to')
            order = arc.get('order')
            priority = arc.get('priority')
            preferred_label = arc.get('preferredLabel')
            
            linkbase_pre.presentation_arcs.append(
                PresentationArc(from_label, to_label, order, priority, preferred_label)
            )
        
        print(f"Added {len(linkbase_pre.presentation_arcs)} arcs to linkbase_pre")
        
        # Show a sample of the added arcs
        for i, arc in enumerate(linkbase_pre.presentation_arcs[:5]):
            print(f"  Arc {i+1}: From={arc.from_label}, To={arc.to_label}, Order={arc.order}")
            
    except Exception as e:
        print(f"Error adding arcs: {str(e)}")



