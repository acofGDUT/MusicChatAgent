# app/services/music/__init__.py

from .user_service import user_service
from .playlist_service import playlist_service
from .song_service import song_service
from .search_service import search_service

# __all__ 告诉 Python：当别人从这个包导入东西时，只允许他们拿走这四个对象
__all__ = [
    "user_service",
    "playlist_service",
    "song_service",
    "search_service"
]