"""Connector abstraction for applying suggestions to target platforms."""

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract base class for platform connectors."""

    @abstractmethod
    async def apply_field(self, suggestion: dict[str, Any]) -> tuple[bool, str]:
        """
        Apply a single field suggestion to the target platform.
        Returns (success: bool, error_message: str).
        """

    @abstractmethod
    async def read_field(
        self, page_url: str, field_type: str, selector: str
    ) -> str:
        """
        Read the live value of a field for verification.
        Returns the current live value.
        """

    @abstractmethod
    async def rollback_field(self, suggestion: dict[str, Any]) -> tuple[bool, str]:
        """
        Rollback a previously applied field to its previous value.
        Returns (success: bool, error_message: str).
        """