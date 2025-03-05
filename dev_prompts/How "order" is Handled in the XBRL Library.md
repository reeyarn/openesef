# How "order" is Handled in the XBRL Library

Based on the provided code snippet and previous information, I can now explain the complete flow of how the "order" attribute is processed in presentation linkbases:

# XBRL Presentation Linkbase Loading Analysis

Based on the repository code, I can explain how the `Arc` class processes presentation arcs, but unfortunately, the search results don't provide the complete picture of how the linkbase files are initially loaded.

## Arc Class Implementation

The presentation linkbase arcs are handled in `taxonomy/arc.py` through the `Arc` class. When a presentationArc element is processed, it extracts various attributes including the `order` value [2](https://github.com/fractalexperience/xbrl/blob/master/taxonomy/arc.py):

```python
class Arc(ebase.XmlElementBase):
    def __init__(self, e, container_xlink=None):
        self.xlink = container_xlink
        super().__init__(e)
        # Extract XLINK attributes
        self.xl_from = e.attrib.get(f'{{{const.NS_XLINK}}}from')
        self.xl_to = e.attrib.get(f'{{{const.NS_XLINK}}}to')
        self.arcrole = e.attrib.get(f'{{{const.NS_XLINK}}}arcrole')
        # Extract other attributes including order
        self.order = e.attrib.get('order')
        self.priority = e.attrib.get('priority')
        self.use = e.attrib.get('use')
        self.weight = e.attrib.get('weight')
        self.preferredLabel = e.attrib.get('preferredLabel')
        # Other attribute processing...
        
        # Register the arc in the container's indexes
        if self.xlink is not None:
            self.xlink.arcs_from.setdefault(f'{self.arcrole}|{self.xl_from}', []).append(self)
            self.xlink.arcs_to.setdefault(f'{self.arcrole}|{self.xl_to}', []).append(self)
```

## Presentation Arcrole Constants

The code also defines constants for the presentation arcrole in `base/const.py` [1](https://github.com/fractalexperience/xbrl/blob/master/base/const.py):

```python
# Presentation
PARENT_CHILD_ARCROLE = 'http://www.xbrl.org/2003/arcrole/parent-child'
```

This matches the arcrole in your example XML:
```xml
<link:presentationArc xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" ...>
```

## Order Value Handling

From the code, we can confirm that:

1. The `Arc` class does load and store the `order` value from presentation arcs
2. The value is stored as a string (since it uses `e.attrib.get('order')` without type conversion)
3. The Arc class organizes arcs in collections by their arcrole and from/to attributes

The `order` attribute is important in presentation linkbases as it determines the display order of concepts in the taxonomy presentation tree.

Unfortunately, the search results don't provide the specific code from `taxonomy/linkbase.py` that would show how the presentation linkbase files (*_pre.xml) are initially loaded and processed. To get that information, we would need to examine that specific file in the repository.

## Initial Loading of Linkbase Files

In `linkbase.py`, the code loads presentation linkbase files through this flow:

1. When a linkbase file (like *_pre.xml) is loaded, an instance of the `Linkbase` class is created
2. The parser configuration maps XML elements to their handler methods:
   ```python
   parsers = {
       f'{{{const.NS_LINK}}}presentationLink': self.l_link,
       # other parsers...
   }
   ```
3. When a `<link:presentationLink>` element is encountered, the `l_link` method creates an `XLink` object:
   ```python
   def l_link(self, e):
       xl = xlink.XLink(e, self)
       self.links.append(xl)
   ```

## Processing the Arc Elements

The created `XLink` object (in `xlink.py`) then:

1. Contains parsers for different elements, including presentation arcs:
   ```python
   parsers = {
       # ...
       f'{{{const.NS_LINK}}}presentationArc': self.l_arc,
       # ...
   }
   ```

2. When a presentation arc is encountered, it calls the `l_arc` method which creates an `Arc` object:
   ```python
   def l_arc(self, e):
       arc.Arc(e, self)
   ```

3. In `taxonomy/arc.py`, the `Arc` class constructor extracts the "order" attribute:
   ```python
   def __init__(self, e, container_xlink=None):
       # ...
       self.order = e.attrib.get('order')  # Gets "10660.00" from your example
       # ...
   ```

## Establishing Relationships Using Order

The `XLink` class later compiles the relationships in its `compile()` method, which:

1. Identifies objects related by arcs (from/to relationships)
2. Connects objects using the appropriate connection method:
   ```python
   def conn_cc(self, a, c_from, c_to):
       # ...
       c_from.chain_dn.setdefault(bs_key, []).append(
           data_wrappers.BaseSetNode(c_to, 0, a, False, c_to.get_label())
       )
       # ...
   ```

3. When creating a `BaseSetNode`, it passes the entire arc object (`a`), which includes the `order` value

## Use of the Order Value

Example xml record: `<link:presentationArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" xlink:from="us-gaap_RevenuesAbstract" xlink:to="tsla_SalesRevenueAutomotive" order="10660.00" priority="2" use="optional" preferredLabel="http://www.xbrl.org/2003/role/totalLabel"/>`

The order value (like "10660.00" in your example) is used to:

1. Determine the relative position of child elements in the presentation hierarchy
2. Sort sibling concepts when displaying the taxonomy presentation tree
3. Maintain the sequence specified by the taxonomy author

Typically, when rendering the presentation hierarchy, the application would sort the nodes in the `chain_dn` collection based on the `order` attribute to ensure proper sequencing of the elements.

The order values don't need to be consecutive numbers - they can have gaps (like 10, 20, 30) to allow for later insertion of elements without renumbering the entire hierarchy.