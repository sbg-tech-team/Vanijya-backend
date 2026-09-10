from app.modules.profile.data.models import (
    User,
    Profile,
    Role,
    Commodity,
    Interest,
    Profile_Commodity,
    Business,
    UserEmbedding,
)

__all__ = [
    "router",
    "User",
    "Profile",
    "Role",
    "Commodity",
    "Interest",
    "Profile_Commodity",
    "Business",
    "UserEmbedding",
]


# `router` is exported lazily (PEP 562). Importing it eagerly here would mean that
# any `from app.modules.profile.data.models import ...` elsewhere pulls in the whole
# presentation layer, which is how the profile <-> onboarding <-> post import
# cycles arose. `from app.modules.profile import router` still works.
def __getattr__(name):
    if name == "router":
        from app.modules.profile.presentation.router import router as _r
        return _r
    raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")
