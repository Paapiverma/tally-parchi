"""
config.py – loads .env and exposes typed settings.
"""
import sys
import os
from dotenv import load_dotenv

if getattr(sys, 'frozen', False):
    basedir = os.path.dirname(sys.executable)
else:
    basedir = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

    TALLY_HOST: str = os.getenv("TALLY_HOST", "localhost")
    TALLY_PORT: int = int(os.getenv("TALLY_PORT", "9000"))
    TALLY_COMPANY: str = os.getenv("TALLY_COMPANY", "")

    APP_EMAIL: str = os.getenv("APP_EMAIL", "")
    APP_PASSWORD: str = os.getenv("APP_PASSWORD", "")

    @property
    def tally_url(self) -> str:
        return f"http://{self.TALLY_HOST}:{self.TALLY_PORT}"


config = Config()
