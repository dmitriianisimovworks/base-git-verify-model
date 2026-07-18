import asyncio
import os
import time
import webbrowser
from pathlib import Path

import aiohttp

CLIENT_ID = os.environ.get("GITVERIFY_CLIENT_ID", "REPLACE_WITH_YOUR_CLIENT_ID")
SCOPE = "read:user"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
TOKEN_PATH = Path.home() / ".config" / "gitverify" / "token"


async def login() -> str:
    async with aiohttp.ClientSession(headers={"Accept": "application/json"}) as session:
        async with session.post(
            DEVICE_CODE_URL, data={"client_id": CLIENT_ID, "scope": SCOPE}
        ) as resp:
            resp.raise_for_status()
            device = await resp.json()

        print(
            f"gitverify never sees your password. Enter this code at "
            f"{device['verification_uri']}: {device['user_code']}"
        )
        try:
            webbrowser.open(device["verification_uri"])
        except webbrowser.Error:
            pass
        print("waiting for you to authorize...")

        interval = device["interval"]
        deadline = time.monotonic() + device["expires_in"]

        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            async with session.post(
                TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": CLIENT_ID,
                    "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            ) as resp:
                payload = await resp.json()

            if "access_token" in payload:
                _save_token(payload["access_token"])
                return payload["access_token"]

            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval = payload.get("interval", interval + 5)
                continue
            raise RuntimeError(f"device flow failed: {payload}")

    raise RuntimeError("device flow timed out, run 'gitverify auth login' again")


def _save_token(token: str) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token)
    TOKEN_PATH.chmod(0o600)


def load_token() -> str | None:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    return None


def logout() -> bool:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        return True
    return False
