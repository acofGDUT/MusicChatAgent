# app/core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "MusicChatAgent"
    NODE_API_URL: str = "http://localhost:3300"
    # 路径建议使用绝对路径防止报错
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    COOKIE_FILE_PATH: str = os.path.join(BASE_DIR, "data", "cookie.txt")
    USER_ID: str = os.getenv("QQ_ID")

settings = Settings()