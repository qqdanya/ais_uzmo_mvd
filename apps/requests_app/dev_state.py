"""Tiny, dependency-free shared state for dev-only background jobs.

Kept separate from dev_views.py so apps.accounts/apps.audit can check
"is a heavy dev job running right now" without importing dev_views.py
itself, which pulls in apps.accounts.views (admin_required) and would be
a circular import from apps.accounts.views back to here.
"""
from django.core.cache import cache

DEV_SEED_PROGRESS_CACHE_KEY = "dev_seed_progress"
DEV_SEED_CANCEL_CACHE_KEY = "dev_seed_cancel"


class SeedCancelled(Exception):
    """Raised from the seed command's progress_callback, between organs,
    once a stop has been requested from /dev/seed/stop/ - lets a running
    generation unwind after the organ it's currently on instead of being
    killed mid-transaction."""


def is_dev_seed_running():
    state = cache.get(DEV_SEED_PROGRESS_CACHE_KEY)
    return bool(state and state.get("running"))
