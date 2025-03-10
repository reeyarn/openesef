"""Version information for OpenESEF"""

import tomli

def _get_version():
    with open("pyproject.toml", "rb") as f:
        return tomli.load(f)["project"]["version"]

__version__ = _get_version()
PICKLE_VERSION = 1     # Pickle format version
PARQUET_VERSION = 1    # Parquet format version 