"""Encrypted KhDiamond credentials and automatic session renewal."""
from __future__ import annotations

import json
import os
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken

AJAX_URL = "https://khdiamond.net/wp-admin/admin-ajax.php"
ACCOUNT_URL = "https://khdiamond.net/my-account/"
DEFAULT_KEY_PATH = "/root/khdiamond/credential.key"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
              "Gecko/20100101 Firefox/149.0")


def key_path() -> Path:
    return Path(os.environ.get("KH_DIAMOND_CREDENTIAL_KEY_FILE", DEFAULT_KEY_PATH))


def _load_or_create_key() -> bytes:
    path = key_path()
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key + b"\n")
    except FileExistsError:
        return path.read_bytes().strip()
    return key


def credential_path(user_dir: Path) -> Path:
    return Path(user_dir) / "credentials.enc"


def save_credentials(user_dir: Path, username: str, password: str) -> None:
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    encrypted = Fernet(_load_or_create_key()).encrypt(payload)
    destination = credential_path(user_dir)
    temporary = destination.with_suffix(".enc.tmp")
    temporary.write_bytes(encrypted)
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def load_credentials(user_dir: Path) -> tuple[str, str] | None:
    path = credential_path(user_dir)
    if not path.exists():
        return None
    try:
        payload = Fernet(_load_or_create_key()).decrypt(path.read_bytes())
        data = json.loads(payload.decode("utf-8"))
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        return (username, password) if username and password else None
    except (InvalidToken, ValueError, KeyError, json.JSONDecodeError):
        return None


def delete_credentials(user_dir: Path) -> None:
    credential_path(user_dir).unlink(missing_ok=True)


def login_khdiamond(username: str, password: str,
                    cookies_path: Path) -> tuple[bool, str]:
    """Log in through DooPlay and persist a Netscape-format cookie jar."""
    jar = MozillaCookieJar(str(cookies_path))
    session = requests.Session()
    session.cookies = jar
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": ACCOUNT_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://khdiamond.net",
    })
    try:
        response = session.post(AJAX_URL, data={
            "action": "dooplay_login",
            "log": username,
            "pwd": password,
            "rmb": "forever",
            "red": ACCOUNT_URL,
        }, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get("response"):
            jar.save(ignore_discard=True, ignore_expires=True)
            os.chmod(cookies_path, 0o600)
            return True, "Login successful"
        return False, str(result.get("message", "Login failed"))
    except (requests.RequestException, ValueError) as exc:
        return False, f"Login request failed: {type(exc).__name__}"


def login_with_saved_credentials(user_dir: Path,
                                 cookies_path: Path) -> tuple[bool, str]:
    credentials = load_credentials(user_dir)
    if not credentials:
        return False, "No usable saved credentials"
    return login_khdiamond(credentials[0], credentials[1], cookies_path)
