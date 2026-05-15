import asyncio
import base64
import json
import logging
from pathlib import Path

import aiofiles
import aiofiles.ospath
from qqmusic_api import Client, Credential
from qqmusic_api.core import LoginError
from qqmusic_api.models.login import QR, QRCodeLoginEvents, QRLoginType

from app.core.config import settings

logger = logging.getLogger(__name__)

CREDENTIAL_PATH = str(Path(settings.BASE_DIR) / "data" / "credential.json")
GLOBAL_CREDENTIAL: Credential | None = None


async def _ensure_credential_parent_dir() -> None:
    Path(CREDENTIAL_PATH).parent.mkdir(parents=True, exist_ok=True)


async def save_credential(credential: Credential) -> None:
    await _ensure_credential_parent_dir()
    async with aiofiles.open(CREDENTIAL_PATH, "w", encoding="utf-8") as f:
        await f.write(credential.model_dump_json(indent=2))


async def load_credential() -> Credential | None:
    if not await aiofiles.ospath.exists(CREDENTIAL_PATH):
        return None
    async with aiofiles.open(CREDENTIAL_PATH, "r", encoding="utf-8") as f:
        content = await f.read()
    if not content.strip():
        return None
    return Credential.model_validate(json.loads(content))


async def ensure_credential_loaded() -> bool:
    global GLOBAL_CREDENTIAL
    if GLOBAL_CREDENTIAL is not None:
        return True

    credential = await load_credential()
    if credential is None:
        return False

    GLOBAL_CREDENTIAL = credential
    return True


async def check_or_refresh_credential() -> dict:
    global GLOBAL_CREDENTIAL

    ready = await ensure_credential_loaded()
    if not ready or GLOBAL_CREDENTIAL is None:
        return {"authenticated": False, "reason": "credential_not_found"}

    try:
        async with Client(credential=GLOBAL_CREDENTIAL) as client:
            expired = await client.login.check_expired()
            if not expired:
                return {"authenticated": True, "refreshed": False}

            refreshed = await client.login.refresh_credential()
            GLOBAL_CREDENTIAL = refreshed
            await save_credential(refreshed)
            return {"authenticated": True, "refreshed": True}
    except Exception as e:
        logger.exception("检查/刷新凭证失败")
        return {"authenticated": False, "reason": f"check_failed: {e}"}


async def clear_credential() -> dict:
    """清空本地凭证并重置内存凭证。"""
    global GLOBAL_CREDENTIAL
    GLOBAL_CREDENTIAL = None

    await _ensure_credential_parent_dir()
    async with aiofiles.open(CREDENTIAL_PATH, "w", encoding="utf-8") as f:
        await f.write("{}")

    return {"status": "success"}


class QRLoginManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._qr: QR | None = None

    @staticmethod
    def _event_to_status(event: QRCodeLoginEvents) -> str:
        mapping = {
            QRCodeLoginEvents.DONE: "done",
            QRCodeLoginEvents.SCAN: "scan",
            QRCodeLoginEvents.CONF: "confirm",
            QRCodeLoginEvents.TIMEOUT: "timeout",
            QRCodeLoginEvents.REFUSE: "refuse",
        }
        return mapping.get(event, "error")

    async def create_qr(self) -> dict:
        async with self._lock:
            async with Client() as client:
                qr = await client.login.get_qrcode(QRLoginType.QQ)

            self._qr = qr
            return {
                "identifier": qr.identifier,
                "mime_type": qr.mimetype,
                "image_base64": base64.b64encode(qr.data).decode("utf-8"),
            }

    async def check_qr(self) -> dict:
        global GLOBAL_CREDENTIAL

        async with self._lock:
            if self._qr is None:
                return {"status": "error", "message": "二维码不存在，请先创建二维码"}

            try:
                async with Client() as client:
                    result = await client.login.check_qrcode(self._qr)

                status = self._event_to_status(result.event)
                if result.event == QRCodeLoginEvents.DONE:
                    if result.credential is None:
                        return {"status": "error", "message": "登录成功但未获取到凭证"}
                    GLOBAL_CREDENTIAL = result.credential
                    await save_credential(result.credential)
                    self._qr = None
                    return {
                        "status": "done",
                        "musicid": result.credential.musicid,
                    }

                if result.event in {QRCodeLoginEvents.TIMEOUT, QRCodeLoginEvents.REFUSE}:
                    self._qr = None

                return {"status": status}
            except LoginError as e:
                logger.exception("二维码登录失败")
                return {"status": "error", "message": str(e)}
            except Exception as e:
                logger.exception("检查二维码状态失败")
                return {"status": "error", "message": str(e)}


qr_login_manager = QRLoginManager()