"""Test-process safety configuration.

This file is imported by pytest before test modules, which guarantees that
LangGraph's serializer observes strict msgpack mode during module import.
"""

import os


os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
