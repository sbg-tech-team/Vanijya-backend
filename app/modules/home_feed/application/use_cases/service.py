# Compatibility shim — imports from individual use case files.
# Existing code that imports from service.py continues to work unchanged.
from app.modules.home_feed.application.use_cases.get_home_feed import *  # noqa: F401, F403
from app.modules.home_feed.application.use_cases.record_engagement import *  # noqa: F401, F403
