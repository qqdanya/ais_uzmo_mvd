"""Shared search helpers for Cyrillic-friendly ORM filtering."""

from django.db.models import Q


def search_query_variants(query):
    """Return text variants for consistent SQLite/PostgreSQL search behaviour.

    SQLite does not reliably handle non-ASCII case-insensitive LIKE, while
    PostgreSQL handles ``__icontains`` better. Searching a small bounded set of
    Python-generated variants keeps filtering in SQL and makes admin/dashboard
    search behave consistently for common Cyrillic case variants.
    """
    value = (query or "").strip()
    if not value:
        return []
    variants = {
        value,
        value.lower(),
        value.upper(),
        value.title(),
        value.capitalize(),
        value.casefold(),
    }
    return [item for item in variants if item]


def build_text_search_q(text_fields, query):
    """Build an OR condition over text fields using shared search variants."""
    condition = Q()
    for term in search_query_variants(query):
        for field_name in text_fields:
            condition |= Q(**{f"{field_name}__icontains": term})
    return condition


def build_mixed_search_q(text_fields, query, *, numeric_fields=()):
    """Build text search plus exact numeric matches for numeric fields."""
    condition = build_text_search_q(text_fields, query)
    value = (query or "").strip()
    if value.isdigit():
        number = int(value)
        for field_name in numeric_fields:
            condition |= Q(**{field_name: number})
    return condition


def apply_text_search(qs, text_fields, query, *, distinct=False):
    """Apply shared text search variants to a queryset."""
    value = (query or "").strip()
    if not value:
        return qs
    condition = build_text_search_q(text_fields, value)
    qs = qs.filter(condition) if condition else qs.none()
    return qs.distinct() if distinct else qs
