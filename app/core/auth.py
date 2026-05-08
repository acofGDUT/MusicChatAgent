import json
import asyncio
import logging
from pathlib import Path
import aiofiles
import aiofiles.ospath
from qqmusic_api import Credential
from app.core.config import settings

logger = logging.getLogger(__name__)

CREDENTIAL_PATH = str(Path(settings.BASE_DIR) / "data" / "credential.json")

# 真正的全局内存变量
GLOBAL_CREDENTIAL: Credential | None = None
_is_initialized = False
_init_lock = None


def _get_init_lock():
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


async def _async_setup_credential_task() -> Credential | None:
    """
    使用主事件循环直接 await qqmusic_api 的异步方法，
    避免“线程 + 新事件循环”的嵌套调用。
    """
    if not await aiofiles.ospath.exists(CREDENTIAL_PATH):
        logger.warning(f"⚠️ 找不到凭证文件 {CREDENTIAL_PATH}，Agent 将无登录态运行")
        return None

    try:
        async with aiofiles.open(CREDENTIAL_PATH, "r", encoding="utf-8") as f:
            content = await f.read()
        data = json.loads(content)
        credential = Credential(**data)

        # 同步校验放入线程，避免阻塞主循环
        await asyncio.to_thread(credential.raise_for_invalid)

        expired = await credential.is_expired()
        if expired:
            logger.info("⏳ 凭证已过期，正在尝试刷新...")
            can_refresh = await credential.can_refresh()
            if can_refresh:
                refreshed = await credential.refresh()
                if refreshed:
                    logger.info("✨ 凭证刷新成功，自动写回 JSON 文件")
                    async with aiofiles.open(CREDENTIAL_PATH, "w", encoding="utf-8") as f:
                        await f.write(json.dumps(credential.as_dict(), indent=4, ensure_ascii=False))
            else:
                logger.error("🚫 凭证失效且无法自动刷新，请手动更新 JSON 文件")

        return credential
    except Exception as e:
        logger.error(f"❌ 解析/刷新凭证失败: {e}")
        return None


async def setup_global_credential():
    global GLOBAL_CREDENTIAL, _is_initialized

    credential = await _async_setup_credential_task()

    if credential:
        GLOBAL_CREDENTIAL = credential
        _is_initialized = True
        logger.info(f"✅ 核心凭证加载就绪！当前用户 ID: {credential.musicid}")
        return True
    else:
        _is_initialized = False
        return False


async def ensure_credential_loaded() -> bool:
    """懒加载凭证：仅在首次需要时初始化，全程并发安全。"""
    global _is_initialized

    if _is_initialized and GLOBAL_CREDENTIAL is not None:
        return True

    lock = _get_init_lock()
    async with lock:
        # 双重检查锁定
        if _is_initialized and GLOBAL_CREDENTIAL is not None:
            return True

        ok = await setup_global_credential()
        return ok