"""Connector package - provides pluggable platform connectors."""

from backend.services.connectors.base import BaseConnector
from backend.services.connectors.replica import ReplicaConnector
from backend.services.connectors.git_static_connector import GitStaticConnector
from backend.services.connectors.wordpress_connector import WordPressConnector


def get_connector(platform: str = "replica") -> "BaseConnector":
    """Get a connector instance for the given platform."""
    if platform == "replica":
        return ReplicaConnector()
    elif platform == "git_static":
        return GitStaticConnector()
    elif platform == "wordpress":
        return WordPressConnector()
    raise ValueError(f"Unknown platform: {platform}")


__all__ = ["BaseConnector", "ReplicaConnector", "GitStaticConnector", "WordPressConnector", "get_connector"]