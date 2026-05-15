from qqmusic_api import Client

import app.core.auth as auth_module
from app.core.auth import ensure_credential_loaded


async def create_client() -> Client:
    """创建并返回已绑定全局凭证的 QQMusic Client。"""
    ready = await ensure_credential_loaded()
    if not ready or auth_module.GLOBAL_CREDENTIAL is None:
        raise RuntimeError("QQ 音乐凭证未初始化，请检查 data/credential.json")
    return Client(credential=auth_module.GLOBAL_CREDENTIAL)
