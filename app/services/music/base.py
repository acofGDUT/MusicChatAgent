from app.core.client import global_storage
from app.core.config import settings


class BaseMusicService:
    def __init__(self):
        self.base_url = settings.NODE_API_URL

    def _get_client(self):
        if global_storage.client is None:
            raise RuntimeError("HTTP client not initialized. Make sure app lifespan has started.")
        return global_storage.client
