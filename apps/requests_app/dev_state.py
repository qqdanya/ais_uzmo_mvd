"""Tiny, dependency-free shared state for dev-only background jobs.

Kept separate from dev_views.py so apps.accounts/apps.audit can check
"is a heavy dev job running right now" without importing dev_views.py
itself, which pulls in apps.accounts.views (admin_required) and would be
a circular import from apps.accounts.views back to here.
"""
from django.core.cache import cache

DEV_SEED_PROGRESS_CACHE_KEY = "dev_seed_progress"


def is_dev_seed_running():
    state = cache.get(DEV_SEED_PROGRESS_CACHE_KEY)
    return bool(state and state.get("running"))
