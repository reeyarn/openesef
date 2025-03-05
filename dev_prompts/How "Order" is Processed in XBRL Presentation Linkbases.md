
# How "Order" is Processed in XBRL Presentation Linkbases

Based on the repository code from the XBRL library, the processing of the "order" attribute in presentation linkbases involves a multi-step flow, starting from the initial loading of linkbase files to its eventual use in organizing taxonomy presentation trees. Below is a comprehensive analysis of this process.

## Initial Loading of Presentation Linkbase Files

The journey begins in `linkbase.py`, where presentation linkbase files (e.g., *_pre.xml) are loaded. An instance of the `Linkbase` class is created, and a parser configuration maps XML elements to their respective handler methods:

```python
parsers = {
    f'{{{const.NS_LINK}}}presentationLink': self.l_link,
    # other parsers...
}
```

When a `<link:presentationLink>` element is encountered, the `l_link` method creates an `XLink` object:

```python
def l_link(self, e):
    xl = xlink.XLink(e, self)
    self.links.append(xl)
```

This sets the stage for processing the individual elements within the linkbase, including presentation arcs.

## Processing Presentation Arcs

The `XLink` class (defined in `xlink.py`) takes over to handle arc elements. It defines its own parsers, including one for presentation arcs:

```python
parsers = {
    f'{{{const.NS_LINK}}}presentationArc': self.l_arc,
    # other elements...
}
```

Upon encountering a `<link:presentationArc>` element, the `l_arc` method triggers the creation of an `Arc` object:

```python
def l_arc(self, e):
    arc.Arc(e, self)
```

The `Arc` class, implemented in `taxonomy/arc.py`, extracts key attributes from the arc element, including the "order" value:

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
        self.order = e.attrib.get('order')  # Stored as a string, e.g., "10660.00"
        self.priority = e.attrib.get('priority')
        self.use = e.attrib.get('use')
        self.weight = e.attrib.get('weight')
        self.preferredLabel = e.attrib.get('preferredLabel')
        # Register the arc in the container's indexes
        if self.xlink is not None:
            self.xlink.arcs_from.setdefault(f'{self.arcrole}|{self.xl_from}', []).append(self)
            self.xlink.arcs_to.setdefault(f'{self.arcrole}|{self.xl_to}', []).append(self)
```

The "order" attribute is retrieved as a string using `e.attrib.get('order')` without type conversion and is stored for later use. The arc is also registered in the `XLink` object’s indexes based on its arcrole and from/to relationships, leveraging the constant defined in `base/const.py`:

```python
PARENT_CHILD_ARCROLE = 'http://www.xbrl.org/2003/arcrole/parent-child'
```

This matches the arcrole in a typical presentation arc, such as:

```xml
<link:presentationArc xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" ...>
```

## Establishing Relationships and Utilizing the Order Value

The `XLink` class compiles relationships between objects in its `compile()` method. It identifies the "from" and "to" objects connected by arcs and establishes these connections using a method like:

```python
def conn_cc(self, a, c_from, c_to):
    c_from.chain_dn.setdefault(bs_key, []).append(
        data_wrappers.BaseSetNode(c_to, 0, a, False, c_to.get_label())
    )
```

Here, the `BaseSetNode` object is created with the arc (`a`), which includes the "order" value. This value plays a critical role in determining the relative position of child elements within the presentation hierarchy. For example, in an XML record like:

```xml
<link:presentationArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" xlink:from="us-gaap_RevenuesAbstract" xlink:to="tsla_SalesRevenueAutomotive" order="10660.00" priority="2" use="optional" preferredLabel="http://www.xbrl.org/2003/role/totalLabel"/>
```

The "order" value (e.g., "10660.00") dictates the sequence of sibling concepts when rendering the taxonomy presentation tree. The application typically sorts nodes in the `chain_dn` collection based on this attribute to ensure the hierarchy reflects the taxonomy author’s intended structure.

## Purpose and Flexibility of the Order Attribute

The "order" attribute is essential for:
1. Defining the display order of concepts in the presentation tree.
2. Sorting sibling elements to maintain a logical sequence.
3. Allowing flexibility in numbering (e.g., using non-consecutive values like 10, 20, 30) to facilitate future insertions without renumbering the entire hierarchy.

While the provided code snippets offer a clear view of how the "order" attribute is extracted and stored, the full picture of linkbase file loading would require examining additional details in `taxonomy/linkbase.py`. Nonetheless, the process outlined—from initial loading to relationship compilation—demonstrates how the XBRL library leverages the "order" attribute to organize and present taxonomy data effectively.
