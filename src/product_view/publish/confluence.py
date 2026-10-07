"""Confluence Cloud REST client: create or update one page, plus its attachments.

Stdlib only (urllib), like the rest of the pipeline. Pages go through the v2 API.
Attachments go through v1, because v2 has no upload endpoint.

Credentials come from the environment only, never config.yaml:

    CONFLUENCE_BASE_URL  https://<site>.atlassian.net
    CONFLUENCE_USER      the Atlassian account email the token belongs to
    ATLASSIAN_TOKEN      API token (id.atlassian.com -> Security -> API tokens)

A `.env` file in the working directory is read if present. Variables already
set in the environment win over it.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .storage import Attachment

ENV_BASE_URL = "CONFLUENCE_BASE_URL"
ENV_USER = "CONFLUENCE_USER"
ENV_TOKEN = "ATLASSIAN_TOKEN"


class ConfluenceError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal KEY=VALUE reader; existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


class Client:
    def __init__(self, base_url: str, user: str, token: str, timeout: float = 60.0) -> None:
        self.base = base_url.rstrip("/")
        if not self.base.endswith("/wiki"):
            self.base += "/wiki"
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        self.auth = f"Basic {creds}"
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "Client":
        load_dotenv()
        missing = [k for k in (ENV_BASE_URL, ENV_USER, ENV_TOKEN) if not os.environ.get(k)]
        if missing:
            raise ConfluenceError(
                "missing environment variable(s): " + ", ".join(missing)
                + " (set them in the environment or in .env)")
        return cls(os.environ[ENV_BASE_URL], os.environ[ENV_USER], os.environ[ENV_TOKEN])

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json_body: Any = None, data: bytes | None = None,
                 headers: dict[str, str] | None = None) -> Any:
        url = self.base + path
        if params:
            url += "?" + urlencode(params)
        hdrs = {"Authorization": self.auth, "Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        req = Request(url, data=data, method=method, headers=hdrs)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:800]
            hint = ""
            if exc.code == 401:
                hint = f" (check {ENV_USER} matches the account that owns {ENV_TOKEN})"
            elif exc.code == 403:
                hint = " (the account lacks permission on this space)"
            raise ConfluenceError(f"{method} {path} -> HTTP {exc.code}{hint}: {detail}") from None
        except URLError as exc:
            raise ConfluenceError(f"{method} {url} failed: {exc.reason}") from None
        return json.loads(raw) if raw else None

    # -- spaces and pages --------------------------------------------------

    def space_id(self, key: str) -> str:
        res = self._request("GET", "/api/v2/spaces", params={"keys": key})
        results = res.get("results", [])
        if not results:
            raise ConfluenceError(
                f"space {key!r} not found, or not visible to this account "
                "(use the space key from the URL: /wiki/spaces/<KEY>/...)")
        return results[0]["id"]

    def find_page(self, space_id: str, title: str) -> dict | None:
        res = self._request("GET", "/api/v2/pages", params={
            "space-id": space_id, "title": title, "status": "current"})
        results = res.get("results", [])
        return results[0] if results else None

    def create_page(self, space_id: str, title: str, body: str,
                    parent_id: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": body},
        }
        if parent_id:
            payload["parentId"] = parent_id
        return self._request("POST", "/api/v2/pages", json_body=payload)

    def update_page(self, page_id: str, title: str, body: str, message: str = "") -> dict:
        current = self._request("GET", f"/api/v2/pages/{page_id}")
        payload = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": body},
            "version": {"number": current["version"]["number"] + 1, "message": message},
        }
        return self._request("PUT", f"/api/v2/pages/{page_id}", json_body=payload)

    def upsert_page(self, space_key: str, title: str, body: str,
                    parent_id: str | None = None, message: str = "") -> tuple[dict, bool]:
        """Update the page with this title in the space, or create it.

        Returns (page, created). Updating in place means every run becomes a
        new version in the page history, rather than a new page.
        """
        sid = self.space_id(space_key)
        existing = self.find_page(sid, title)
        if existing:
            return self.update_page(existing["id"], title, body, message), False
        return self.create_page(sid, title, body, parent_id), True

    def set_full_width(self, page_id: str) -> None:
        """Full-width appearance, the content properties the editor itself
        sets (report-design.md D3). Updated in place when already present."""
        for key in ("content-appearance-published", "content-appearance-draft"):
            path = f"/rest/api/content/{page_id}/property/{key}"
            try:
                current = self._request("GET", path)
            except ConfluenceError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                current = None
            if current is None:
                self._request("POST", f"/rest/api/content/{page_id}/property",
                              json_body={"key": key, "value": "full-width"})
            elif current.get("value") != "full-width":
                self._request("PUT", path, json_body={
                    "key": key, "value": "full-width",
                    "version": {"number": current["version"]["number"] + 1}})

    def page_url(self, page: dict) -> str:
        webui = (page.get("_links") or {}).get("webui", "")
        return self.base + webui if webui else f"{self.base}/pages/{page['id']}"

    # -- attachments -------------------------------------------------------

    def attachments(self, page_id: str) -> dict[str, dict]:
        """The page's attachments by filename."""
        res = self._request("GET", f"/rest/api/content/{page_id}/child/attachment",
                            params={"limit": 200, "expand": "version"})
        return {a["title"]: a for a in res.get("results", [])}

    def download(self, attachment: dict) -> bytes:
        url = self.base + attachment["_links"]["download"]
        req = Request(url, headers={"Authorization": self.auth})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except (HTTPError, URLError):
            return b""  # unknown content: treat as changed and re-upload

    def sync_attachments(self, page_id: str, atts: list[Attachment]) -> tuple[int, int]:
        """Upload new or changed attachments; returns (uploaded, unchanged).

        An unchanged file is skipped (no pointless new attachment version on
        every run). A changed one is updated through v1's PUT "create or
        update", falling back to the attachment's own /data endpoint: Cloud
        has rejected each of them at different times (PUT with HTTP 500 when
        the filename existed, when this was first built; /data with an empty
        HTTP 400 on 2026-10-07).
        """
        existing = self.attachments(page_id)
        uploaded = unchanged = 0
        for att in atts:
            current = existing.get(att.filename)
            if current is None:
                self._upload(f"/rest/api/content/{page_id}/child/attachment", att)
            elif self.download(current) == att.data:
                unchanged += 1
                continue
            else:
                try:
                    self._upload(f"/rest/api/content/{page_id}/child/attachment", att, "PUT")
                except ConfluenceError:
                    self._upload(
                        f"/rest/api/content/{page_id}/child/attachment/{current['id']}/data", att)
            uploaded += 1
        return uploaded, unchanged

    def _upload(self, path: str, att: Attachment, method: str = "POST") -> None:
        boundary = uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            (f'Content-Disposition: form-data; name="file"; filename="{att.filename}"\r\n'
             f"Content-Type: {att.media_type}\r\n\r\n").encode(),
            att.data,
            f"\r\n--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="minorEdit"\r\n\r\ntrue',
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        # Cloud occasionally answers an attachment write with HTTP 500
        # ("transaction rolled back"); the same request then succeeds.
        for attempt in range(3):
            try:
                self._request(
                    method, path, data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                             "X-Atlassian-Token": "no-check"})
                return
            except ConfluenceError as exc:
                if "HTTP 5" not in str(exc) or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
