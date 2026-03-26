from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests


BASE_URL = "http://127.0.0.1:9993"
AUTH_HEADER = "X-ZT1-Auth"

SYSTEM_AUTHTOKEN_PATH = Path("/var/lib/zerotier-one/authtoken.secret")
USER_AUTHTOKEN_PATH = Path.home() / ".config" / "zerotier-gui" / "authtoken.secret"


class ZeroTierError(RuntimeError):
    pass


class ServiceNotReachableError(ZeroTierError):
    pass


class TokenMissingError(ZeroTierError):
    pass


class TokenPermissionError(ZeroTierError):
    pass


class APIError(ZeroTierError):
    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class NetworkPermissionPayload:
    allowManaged: bool = True
    allowGlobal: bool = False
    allowDefault: bool = False
    allowDNS: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        # These four fields map directly to the macOS checkbox labels.
        return {
            "allowManaged": self.allowManaged,
            "allowGlobal": self.allowGlobal,
            "allowDefault": self.allowDefault,
            "allowDNS": self.allowDNS,
        }


class ZeroTierAPI:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._token: Optional[str] = None

    @property
    def token_loaded(self) -> bool:
        return bool(self._token)

    def load_token(self) -> str:
        """
        Load `authtoken.secret` from the standard ZeroTier One location.

        If not readable, callers can catch TokenPermissionError and provide a user override token.
        """

        # Prefer system token (macOS client behavior equivalent).
        try:
            token = SYSTEM_AUTHTOKEN_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError as e:
            raise TokenMissingError(f"Missing system authtoken at {SYSTEM_AUTHTOKEN_PATH}") from e
        except PermissionError as e:
            raise TokenPermissionError(
                f"Permission denied reading {SYSTEM_AUTHTOKEN_PATH}. "
                "A user token override is supported."
            ) from e
        except OSError as e:
            raise TokenPermissionError(f"Failed reading {SYSTEM_AUTHTOKEN_PATH}: {e}") from e

        if not token:
            raise TokenMissingError("System authtoken.secret was empty.")

        self._token = token
        return token

    def load_user_token(self) -> Optional[str]:
        try:
            token = USER_AUTHTOKEN_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        if not token:
            return None
        self._token = token
        return token

    def set_user_token(self, token: str) -> None:
        token = token.strip()
        USER_AUTHTOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_AUTHTOKEN_PATH.write_text(token + "\n", encoding="utf-8")
        # Keep the user token private.
        try:
            os.chmod(USER_AUTHTOKEN_PATH, 0o600)
        except OSError:
            # Non-fatal: best effort.
            pass
        self._token = token

    def import_system_token_with_privilege(self, timeout_s: float = 30.0) -> bool:
        """
        Try a one-shot privileged read of the system authtoken and persist it to the
        user-scoped token path. Returns True on success, False otherwise.
        """
        commands: list[list[str]] = []
        if shutil.which("pkexec") is not None:
            commands.append(["pkexec", "cat", str(SYSTEM_AUTHTOKEN_PATH)])
        if shutil.which("sudo") is not None:
            commands.append(["sudo", "-n", "cat", str(SYSTEM_AUTHTOKEN_PATH)])
        # Flatpak: run privilege escalation on host side.
        if shutil.which("flatpak-spawn") is not None:
            commands.append(["flatpak-spawn", "--host", "pkexec", "cat", str(SYSTEM_AUTHTOKEN_PATH)])
            commands.append(["flatpak-spawn", "--host", "sudo", "-n", "cat", str(SYSTEM_AUTHTOKEN_PATH)])
            commands.append(["flatpak-spawn", "--host", "cat", str(SYSTEM_AUTHTOKEN_PATH)])

        for cmd in commands:
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            except Exception:
                continue
            if p.returncode != 0:
                continue

            token = (p.stdout or "").strip()
            if not token:
                continue
            self.set_user_token(token)
            return True
        return False

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise TokenMissingError("ZeroTier API token not loaded.")
        return {AUTH_HEADER: self._token}

    def _request_json(self, method: str, path: str, *, json_body: Any = None, timeout_s: float = 2.0) -> Any:
        url = BASE_URL + path
        try:
            resp = self._session.request(
                method=method,
                url=url,
                headers=self._headers(),
                json=json_body,
                timeout=timeout_s,
            )
        except requests.RequestException as e:
            raise ServiceNotReachableError(f"Failed to reach ZeroTier service at {url}: {e}") from e

        if resp.status_code == 401:
            raise APIError("Unauthorized (bad/expired token).", status_code=resp.status_code, body=resp.text)
        if resp.status_code >= 400:
            # Try JSON; fall back to text.
            body: Any
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise APIError(
                f"ZeroTier API error {resp.status_code}: {resp.reason}",
                status_code=resp.status_code,
                body=body,
            )

        if resp.text:
            # Some endpoints return JSON objects/lists; parse it.
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                return resp.json()
            # Best-effort parse.
            try:
                return json.loads(resp.text)
            except Exception:
                return resp.text
        return None

    def get_node_status(self) -> dict[str, Any]:
        return self._request_json("GET", "/status")

    def list_networks(self) -> list[dict[str, Any]]:
        data = self._request_json("GET", "/network")
        if not isinstance(data, list):
            raise APIError("Unexpected /network response (expected a list).", body=data)
        return data

    def get_network(self, network_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/network/{network_id}")

    def join_or_update_network(self, network_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", f"/network/{network_id}", json_body=payload)

    def leave_network(self, network_id: str) -> None:
        self._request_json("DELETE", f"/network/{network_id}")

    def list_peers(self) -> list[dict[str, Any]]:
        data = self._request_json("GET", "/peer")
        if not isinstance(data, list):
            raise APIError("Unexpected /peer response (expected a list).", body=data)
        return data

