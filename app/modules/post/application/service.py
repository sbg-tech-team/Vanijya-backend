# Compatibility shim — delegates everything to the use_cases layer.
# The router imports this module as:
#   from app.modules.post.application import service
# and then calls e.g. service.create_post(...).

from app.modules.post.application.use_cases.service import *  # noqa: F401, F403
from app.modules.post.application.use_cases.service import __all__  # noqa: F401
