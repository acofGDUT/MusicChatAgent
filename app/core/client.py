# app/core/client.py
import httpx

class GlobalClient:
    client: httpx.AsyncClient = None

global_storage = GlobalClient()