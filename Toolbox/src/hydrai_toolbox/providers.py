"""Provider implementations for Toolbox."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import tomllib
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass


@dataclass
class BraveWebSearchProvider:
    api_key: str
    timeout: int = 15

    def search(self, query: str, count: int = 5) -> dict:
        if not self.api_key:
            return {"error": "missing brave api key"}
        params = urllib.parse.urlencode({"q": str(query or ""), "count": max(1, min(int(count), 20))})
        url = f"https://api.search.brave.com/res/v1/web/search?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            return {"error": f"web search failed: {exc}"}
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                }
            )
        return {"results": results}


@dataclass
class HimalayaEmailProvider:
    bin_name: str = "himalaya"
    timeout: int = 60

    def _base_cmd(self, account: str = "") -> list[str]:
        _ = account
        return [self.bin_name]

    def _with_account(self, cmd: list[str], account: str) -> list[str]:
        if account:
            cmd += ["--account", account]
        return cmd

    def _run(self, cmd: list[str], stdin_text: str | None = None) -> tuple[int, str, str]:
        proc = subprocess.run(
            cmd,
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=self.timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _sent_copy_append_failed(self, stdout: str, stderr: str) -> bool:
        text = f"{stdout}\n{stderr}".lower()
        return "cannot add imap message" in text or "folder not exist" in text

    def search(self, query: str, limit: int = 10, account: str = "", folder: str = "") -> dict:
        cmd = self._base_cmd(account) + ["envelope", "list", "--output", "json", "--page-size", str(max(1, int(limit)))]
        cmd = self._with_account(cmd, account)
        if folder:
            cmd += ["--folder", folder]
        if query:
            cmd += shlex.split(str(query))
        code, out, err = self._run(cmd)
        if code != 0:
            return {"error": f"email search failed: {err.strip() or out.strip()}"}
        try:
            envelopes = json.loads(out or "[]")
        except json.JSONDecodeError:
            return {"error": "email search returned invalid JSON"}
        return {"messages": envelopes}

    def read(self, message_id: str, account: str = "") -> dict:
        cmd = self._base_cmd(account) + ["message", "read", str(message_id)]
        cmd = self._with_account(cmd, account)
        code, out, err = self._run(cmd)
        if code != 0:
            return {"error": f"email read failed: {err.strip() or out.strip()}"}
        return {"id": str(message_id), "body": out}

    def _render_template(
        self,
        to: list[str],
        subject: str,
        body: str,
        from_addr: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> str:
        lines = [f"To: {', '.join(to)}", f"Subject: {subject}"]
        if from_addr:
            lines.insert(0, f"From: {from_addr}")
        if cc:
            lines.append(f"Cc: {', '.join(cc)}")
        if bcc:
            lines.append(f"Bcc: {', '.join(bcc)}")
        lines += ["", body]
        return "\n".join(lines)

    def _resolve_from_addr(self, account: str) -> str:
        env_from = os.environ.get("HYDRAI_TOOLBOX_EMAIL_FROM", "").strip()
        if env_from:
            return env_from
        if "@" in account:
            return account
        cfg_path = os.environ.get("HIMALAYA_CONFIG", "").strip()
        if not cfg_path:
            return ""
        try:
            with open(cfg_path, "rb") as handle:
                cfg = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return ""
        accounts = cfg.get("accounts", {})
        if not isinstance(accounts, dict):
            return ""
        item = accounts.get(account, {})
        if not isinstance(item, dict):
            return ""
        email = item.get("email", "")
        return str(email).strip() if isinstance(email, str) else ""

    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        account: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        template = self._render_template(
            to,
            subject,
            body,
            from_addr=self._resolve_from_addr(account),
            cc=cc,
            bcc=bcc,
        )
        cmd = self._base_cmd(account) + ["template", "send"]
        cmd = self._with_account(cmd, account)
        code, out, err = self._run(cmd, stdin_text=template)
        if code != 0:
            if self._sent_copy_append_failed(out, err):
                warning = err.strip() or out.strip() or "message delivered but sent copy append failed"
                return {"ok": True, "warning": warning}
            return {"error": f"email send failed: {err.strip() or out.strip()}"}
        return {"ok": True}

    def draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        account: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        template = self._render_template(
            to,
            subject,
            body,
            from_addr=self._resolve_from_addr(account),
            cc=cc,
            bcc=bcc,
        )
        draft_id = str(uuid.uuid4())
        draft_dir = os.path.join(tempfile.gettempdir(), "hydrai-toolbox-email-drafts")
        os.makedirs(draft_dir, exist_ok=True)
        draft_path = os.path.join(draft_dir, f"{draft_id}.eml")
        with open(draft_path, "w", encoding="utf-8") as handle:
            handle.write(template)
        return {"ok": True, "draft_id": draft_id, "path": draft_path}
