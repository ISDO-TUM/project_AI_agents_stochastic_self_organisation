"""Market-Hive (ECSAS) engine package.

Importing the package registers the engine's blackboard/auction tools with the
shared tool registry (see ``server.market_hive.tools``). The app loads this
package at startup via ``server.market_hive.routes``.
"""

from server.market_hive import tools as _tools  # import triggers tool self-registration
