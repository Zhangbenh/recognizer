"""Domain-level constants shared by application services and state machine."""

from __future__ import annotations

MODE_NORMAL = "normal"
MODE_SAMPLING = "sampling"

HOME_OPTION_NORMAL = MODE_NORMAL
HOME_OPTION_SAMPLING = MODE_SAMPLING

DEFAULT_STATS_PAGE_SIZE = 4

# Default runtime timeouts (seconds). Values align with the design documents.
INFER_TIMEOUT_SECONDS = 3.0
DISPLAY_TIMEOUT_SECONDS = 5.0
RECORD_TIMEOUT_SECONDS = 1.0

