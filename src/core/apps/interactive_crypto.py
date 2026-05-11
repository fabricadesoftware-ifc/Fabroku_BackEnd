import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings


@lru_cache(maxsize=1)
def interactive_fernet() -> Fernet:
    key_material = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(key_material)
    return Fernet(key)


def encrypt_interactive_text(value: str) -> bytes:
    return interactive_fernet().encrypt(value.encode('utf-8'))


def decrypt_interactive_text(value: bytes | memoryview) -> str:
    return interactive_fernet().decrypt(bytes(value)).decode('utf-8', errors='replace')
