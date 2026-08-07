"""Shared add-on identity and conservative defaults."""

ADDON_VERSION = (0, 1, 0)
ADDON_VERSION_STRING = ".".join(str(part) for part in ADDON_VERSION)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
