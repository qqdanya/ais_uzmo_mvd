"""Caps how many large exports can be built at once.

Building a big XLSX/CSV export blocks the request/response cycle end to end
(see exports.py/downloads.py - there's no task queue, the gunicorn worker is
tied up for the whole build+save). With only a handful of workers, a few
people exporting large tables at the same moment could starve every worker
and make the app unresponsive for everyone else. This caps concurrent large
exports to a small number of slots, shared across all gunicorn workers via
the cache (real Redis in production, per docs/DEPLOY_LINUX.md).
"""

import uuid
from contextlib import contextmanager

from django.core.cache import cache

HEAVY_EXPORT_MAX_CONCURRENT = 2
# A bit above the gunicorn --timeout in docs/DEPLOY_LINUX.md (120s), so a
# worker killed mid-export (timeout, OOM) still frees its slot on its own
# instead of holding it forever - self-healing beats relying on cleanup code
# that a killed worker never gets to run.
HEAVY_EXPORT_SLOT_TTL_SECONDS = 150


class ExportBusyError(Exception):
    """Raised when every heavy-export slot is currently taken."""


def _slot_key(index):
    return f"heavy-export-slot:{index}"


@contextmanager
def heavy_export_slot():
    token = uuid.uuid4().hex
    acquired_index = None
    for index in range(HEAVY_EXPORT_MAX_CONCURRENT):
        # cache.add is a no-op (returns False) if the key already exists, so
        # this is an atomic "claim this slot only if it's free" per index.
        if cache.add(_slot_key(index), token, timeout=HEAVY_EXPORT_SLOT_TTL_SECONDS):
            acquired_index = index
            break
    if acquired_index is None:
        raise ExportBusyError
    try:
        yield
    finally:
        key = _slot_key(acquired_index)
        # Only clear it if it's still our token - if the TTL already expired
        # and someone else claimed the slot in the meantime, don't evict them.
        if cache.get(key) == token:
            cache.delete(key)
