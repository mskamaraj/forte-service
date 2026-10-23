"""Pytest configuration for the Forte service test suite.

Ensures the service package root (this directory) is importable as `app.*`,
matching the import style used throughout the application code
(e.g. `from app.api.deps import require_coach`).
"""

import os
import sys

# The service package root is the directory containing this file.
_SERVICE_ROOT = os.path.dirname(os.path.abspath(__file__))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)
