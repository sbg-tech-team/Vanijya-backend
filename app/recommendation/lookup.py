"""The only database access the shared recommendation code needs.

amplify.py and global_taste/ blend persistent taste with Redis session taste.
Between them they touch exactly two tables — commodities and user_global_taste —
and everything else is Redis plus arithmetic. That is why this is a two-method
mixin rather than another repository: the modules already have repositories, and
they only lacked these two reads.

Mixing it into a module's repository means the shared helpers take that
repository instead of a raw Session, which is what kept `repo.session` alive on
fourteen call sites across post, news, groups and connections.
"""
from __future__ import annotations


class AmplifyLookupMixin:
    """Provides all_commodities() and global_taste_rows() over the repository's
    own session, whatever it calls it."""

    def _amplify_session(self):
        # Repositories in this codebase name the session either `db` or `_db`.
        return getattr(self, "db", None) or getattr(self, "_db")

    def all_commodities(self) -> list:
        from app.modules.profile.data.models import Commodity

        return self._amplify_session().query(Commodity).all()

    def global_taste_rows(self, profile_id: int, dimension_type: str) -> list:
        from app.recommendation.global_taste.models import UserGlobalTaste

        return (
            self._amplify_session()
            .query(UserGlobalTaste)
            .filter(
                UserGlobalTaste.profile_id == profile_id,
                UserGlobalTaste.dimension_type == dimension_type,
            )
            .all()
        )
