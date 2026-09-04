from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv
import os

load_dotenv()

limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("VALKEY_URL", "memory://"))