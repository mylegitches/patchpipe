"""Shared application errors."""


class PatchmakerError(Exception):
    """Base error for the POD HD patch maker."""


class ValidationError(PatchmakerError):
    """Invalid user input or API payload."""
