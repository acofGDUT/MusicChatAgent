import os
from pathlib import Path

from langchain_openai import ChatOpenAI

MODEL_NAME = os.getenv("MUSIC_AGENT_MODEL", "glm-4.5-air")
MUSIC_MODEL_BASE_URL = os.getenv("MUSIC_AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MUSIC_MODEL_API_KEY = os.getenv("MUSIC_AGENT_API_KEY", "")
SECONDARY_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MODEL_BASE_URL = os.getenv("OPENAI_API_BASE", "")
MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

MAX_EXECUTOR_REENTRY_WITHOUT_USER = int(os.getenv("MUSIC_AGENT_MAX_EXECUTOR_REENTRY_WITHOUT_USER", "1"))
SUMMARY_TRIGGER_TOKENS = int(os.getenv("MUSIC_AGENT_SUMMARY_TRIGGER_TOKENS", "5000"))
SUMMARY_KEEP_MESSAGES = int(os.getenv("MUSIC_AGENT_SUMMARY_KEEP_MESSAGES", "12"))
ENABLE_SOUL_AUTOTUNE = os.getenv("MUSIC_AGENT_ENABLE_SOUL_AUTOTUNE", "false").lower() == "true"

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
USER_PROFILE_PATH = MEMORY_DIR / "user_profile.md"
SOUL_PATH = MEMORY_DIR / "soul.md"
HISTORY_PATH = MEMORY_DIR / "history.jsonl"

llm0 = ChatOpenAI(
    temperature=0,
    model=SECONDARY_MODEL_NAME,
    openai_api_key=MODEL_API_KEY,
    openai_api_base=MODEL_BASE_URL,
)

llm1 = ChatOpenAI(
    temperature=0,
    model=MODEL_NAME,
    openai_api_key=MUSIC_MODEL_API_KEY,
    openai_api_base=MUSIC_MODEL_BASE_URL,
)
