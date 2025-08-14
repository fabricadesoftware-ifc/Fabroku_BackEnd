from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SESSION_DIR = Path(os.getenv("FABROKU_HOME", Path.home() / ".fabroku"))
SESSION_FILE = SESSION_DIR / "session.json"


@dataclass
class Session:
	email: str


def save_session(email: str) -> None:
	SESSION_DIR.mkdir(parents=True, exist_ok=True)
	SESSION_FILE.write_text(json.dumps({"email": email}), encoding="utf-8")


def load_session() -> Optional[Session]:
	if not SESSION_FILE.exists():
		return None
	try:
		data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
		email = data.get("email")
		if not email:
			return None
		return Session(email=email)
	except Exception:
		return None


def clear_session() -> None:
	try:
		if SESSION_FILE.exists():
			SESSION_FILE.unlink()
	except Exception:
		pass 