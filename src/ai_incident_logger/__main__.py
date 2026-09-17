"""Allow ``python -m ai_incident_logger`` as a CLI entry point."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
