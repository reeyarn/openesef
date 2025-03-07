"""
XBRL filing loader with versioned caching support.

This module provides functionality to load XBRL filings from SEC EDGAR, with support
for versioned caching of parsed objects. The caching system handles:
- Versioned pickle files for Instance and Taxonomy objects
- XML content caching
- In-memory filesystem (memfs) state preservation

The version number is centrally managed in openesef.__init__.PICKLE_VERSION.
"""

import gzip
import pickle
import logging
from openesef.version import PICKLE_VERSION

#from datetime import datetime
#import fs
#import sys
#import json

logger = logging.getLogger("main.openesf.edgar.verpkl")

class VersionedPickle:
    """
    Version-controlled pickle serialization for XBRL objects.
    
    Handles serialization of objects along with their memfs content, ensuring version
    compatibility when loading cached data. Version number is controlled by 
    PICKLE_VERSION in openesef.__init__.
    
    Usage:
        # Saving objects
        VersionedPickle.save(xid, "instance.pkl.gz", memfs=memfs)
        
        # Loading objects
        xid = VersionedPickle.load("instance.pkl.gz", memfs=memfs)
    
    The class automatically handles:
    - Version checking during loads
    - memfs content preservation
    - Compression via gzip
    """
    CURRENT_VERSION = PICKLE_VERSION

    def __init__(self, data, version=CURRENT_VERSION, memfs_content=None):
        """Initialize with data and optional memfs content."""
        self.version = version
        self.data = data
        self.memfs_content = memfs_content

    @staticmethod
    def _clean_for_pickle(obj):
        """Remove unpickleable attributes."""
        # List of attributes that can't be pickled
        unpickleable_attrs = [
            'memfs', '_lock', '_thread_lock', 
            '_reader_lock', '_writer_lock', 'lock',
            '_cache_lock', '_fs_lock', 'parser'
        ]
        
        saved_attrs = {}
        
        def clean_object(o, prefix=''):
            """Recursively clean object and its attributes."""
            if o is None:
                return
                
            # Clean the main attributes
            for attr in unpickleable_attrs:
                if hasattr(o, attr):
                    full_attr = f"{prefix}{attr}" if prefix else attr
                    saved_attrs[full_attr] = getattr(o, attr)
                    setattr(o, attr, None)
            
            # Clean nested objects
            for nested_attr in ['container_pool', 'root', 'tree', '_taxonomy']:
                if hasattr(o, nested_attr):
                    nested_obj = getattr(o, nested_attr)
                    if nested_obj is not None:
                        clean_object(nested_obj, f"{prefix}{nested_attr}.")
        
        # Start cleaning from the top object
        clean_object(obj)
        return saved_attrs

    @staticmethod
    def _restore_attrs(obj, saved_attrs, memfs=None):
        """Restore previously removed attributes."""
        def restore_object(o, attrs):
            """Recursively restore object attributes."""
            for attr, value in attrs.items():
                if '.' in attr:
                    # Handle nested attributes
                    parts = attr.split('.')
                    current_obj = o
                    # Navigate to the correct object
                    for part in parts[:-1]:
                        if hasattr(current_obj, part):
                            current_obj = getattr(current_obj, part)
                        else:
                            break
                    # Set the attribute
                    if current_obj is not None:
                        setattr(current_obj, parts[-1], 
                               value if value is not None else memfs)
                else:
                    # Set direct attributes
                    setattr(o, attr, value if value is not None else memfs)
        
        restore_object(obj, saved_attrs)

    @classmethod
    def save(cls, data, filename, memfs=None):
        """
        Save data with version information and optional memfs content.
        
        Args:
            data: Object to serialize
            filename: Path to save the gzipped pickle
            memfs: Optional fs.open_fs('mem://') instance to preserve
        """
        try:
            # Capture memfs content
            memfs_content = None
            if memfs:
                try:
                    memfs_content = {}
                    for fname in memfs.listdir('/'):
                        if memfs.isfile(fname):
                            memfs_content[fname] = memfs.readtext(fname)
                except Exception as e:
                    logger.warning(f"Could not capture memfs content: {e}")

            # Remove unpickleable attributes
            saved_attrs = cls._clean_for_pickle(data)

            # Create and save versioned data
            versioned_data = cls(data, memfs_content=memfs_content)
            with gzip.open(filename, 'wb') as f:
                pickle.dump(versioned_data, f)

            # Restore attributes
            cls._restore_attrs(data, saved_attrs, memfs)

        except Exception as e:
            logger.error(f"Failed to save pickle to {filename}: {e}")
            raise

    @classmethod
    def load(cls, filename, memfs=None):
        """
        Load versioned data, checking compatibility and restoring memfs.
        
        Args:
            filename: Path to the gzipped pickle
            memfs: Optional fs.open_fs('mem://') instance to restore into
            
        Raises:
            ValueError: If version mismatch or invalid format
        """
        try:
            with gzip.open(filename, 'rb') as f:
                versioned_data = pickle.load(f)

            if not isinstance(versioned_data, cls):
                raise ValueError("Cached file is not version-controlled")

            if versioned_data.version != cls.CURRENT_VERSION:
                raise ValueError(f"Cache version mismatch. Expected {cls.CURRENT_VERSION}, got {versioned_data.version}")

            data = versioned_data.data

            # Restore memfs content
            if memfs and versioned_data.memfs_content:
                for fname, content in versioned_data.memfs_content.items():
                    with memfs.open(fname, 'w') as f:
                        f.write(content)

            # Restore memfs references
            saved_attrs = {'memfs': memfs}
            if hasattr(data, 'container_pool'):
                saved_attrs['container_pool.memfs'] = memfs
            cls._restore_attrs(data, saved_attrs)

            return data

        except Exception as e:
            logger.error(f"Failed to load pickle: {e}")
            raise