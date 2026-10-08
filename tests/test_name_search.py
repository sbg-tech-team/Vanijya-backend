"""
tests/test_name_search.py

People search matches a name in any stored language (profile.name_i18n).
Checks the SQL that is built — executing it needs Postgres (jsonb_each_text).

    pytest tests/test_name_search.py -v
"""
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.modules.connections.data.repository import ConnectionsRepository


def _sql(q):
    clause = ConnectionsRepository(Session())._name_or_business_matches(q)
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_search_matches_typed_name_every_language_and_business():
    sql = _sql("akshay")
    assert "profile.name ILIKE '%%akshay%%'" in sql or "profile.name ILIKE '%akshay%'" in sql
    assert "jsonb_each_text(profile.name_i18n)" in sql          # any language version
    assert "NOT IN ('auto', 'failed')" in sql                     # not the bookkeeping lists
    assert "business_name ILIKE" in sql                           # business search unchanged


def test_search_term_is_bound_not_pasted_into_sql():
    clause = ConnectionsRepository(Session())._name_or_business_matches("x' OR 1=1 --")
    sql = str(clause.compile(dialect=postgresql.dialect()))
    assert "OR 1=1" not in sql                                     # stays a parameter
