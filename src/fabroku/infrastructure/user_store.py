from __future__ import annotations

import json
import re
from pathlib import Path
import os
import secrets
from typing import Optional

BASE_DIR = Path(os.getenv("FABROKU_HOME", Path.home() / ".fabroku")) / "users"


def _sanitize_email(email: str) -> str:
	return re.sub(r"[^a-zA-Z0-9_.-]", "_", email)


def get_or_create_user_tag(email: str) -> str:
	BASE_DIR.mkdir(parents=True, exist_ok=True)
	name = _sanitize_email(email)
	file = BASE_DIR / f"{name}.json"
	if file.exists():
		try:
			data = json.loads(file.read_text(encoding="utf-8"))
			tag = data.get("tag")
			if tag:
				return tag
		except Exception:
			pass
	# cria tag nova
	tag = secrets.token_hex(8)
	file.write_text(json.dumps({"tag": tag}), encoding="utf-8")
	return tag 