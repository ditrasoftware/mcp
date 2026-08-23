"""AnticaFarmacia MCP (FastMCP 4.x, refactored architecture).

This package follows the refactored artifact architecture:
- Canonical artifact registrations in `artifacts/`
- Compatibility wrappers and adapters in `providers/`
- Cross-cutting middleware in `middleware/`
- Capability contracts and taxonomy in `capability/`
"""

from .server import create_mcp  # noqa: F401
from .version import __version__  # noqa: F401
