"""OpenESEF package"""

from .version import PICKLE_VERSION, PARQUET_VERSION

# Import subpackages
from . import base
from . import taxonomy
from . import instance
from . import ixbrl
from . import util
from . import edgar
from . import filings_xbrl_org
from . import engines  # Import engines last since it depends on other modules
# Don't import resolver directly here
# Remove: from . import resolver
