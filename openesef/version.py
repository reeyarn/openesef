"""Version information for OpenESEF"""

import os
import tomli
import pkg_resources

def _get_version():
    # Try to read from pyproject.toml in package data
    try:
        pyproject_path = pkg_resources.resource_filename('openesef', 'pyproject.toml')
        with open(pyproject_path, "rb") as f:
            return tomli.load(f)["project"]["version"]
    except (FileNotFoundError, KeyError):
        # Fallback to hardcoded version if file not found
        print(f"Warning: pyproject.toml not found in package data. Using hardcoded version.")
        return "0.3.8"

__version__ = _get_version()
PICKLE_VERSION = 1     # Pickle format version
PARQUET_VERSION = 1    # Parquet format version 