"""Compatibility shim for older templates; prefer loading account_tags."""

from .account_tags import admin_multiselect, register  # noqa: F401
