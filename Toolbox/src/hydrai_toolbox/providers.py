"""Provider implementations for Toolbox."""

from __future__ import annotations

import json
import base64
import imaplib
import os
import shlex
import smtplib
import subprocess
import tempfile
import tomllib
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from email import message_from_bytes
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default


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

    def read(self, message_id: str, account: str = "", folder: str = "") -> dict:
        cmd = self._base_cmd(account) + ["message", "read", str(message_id)]
        cmd = self._with_account(cmd, account)
        if folder:
            cmd += ["--folder", folder]
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


@dataclass
class ImapSmtpEmailProvider:
    email: str
    login: str
    password_env: str
    imap_host: str
    imap_port: int
    imap_tls: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_tls: bool = True
    timeout: int = 60
    inbox_folder: str = "INBOX"
    sent_folder: str = "Sent"
    drafts_folder: str = "Drafts"
    trash_folder: str = "Trash"
    imap_id: dict[str, str] | None = None

    def _password(self) -> str:
        value = os.environ.get(self.password_env, "").strip()
        if not value:
            raise RuntimeError(f"missing password env: {self.password_env}")
        return value

    def _imap(self) -> imaplib.IMAP4:
        if self.imap_tls:
            client = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        else:
            client = imaplib.IMAP4(self.imap_host, self.imap_port)
        client.login(self.login, self._password())
        if self.imap_id:
            payload = "(" + " ".join(f'"{key}" "{value}"' for key, value in self.imap_id.items()) + ")"
            client.xatom("ID", payload)
        return client

    def _smtp(self) -> smtplib.SMTP:
        if self.smtp_tls:
            client = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout)
        else:
            client = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout)
            client.ehlo()
            client.starttls()
            client.ehlo()
        client.login(self.login, self._password())
        return client

    def _criteria(self, query: str) -> list[str]:
        terms = shlex.split(str(query or ""))
        criteria: list[str] = []
        for term in terms:
            lowered = term.lower()
            if lowered == "seen":
                criteria.append("SEEN")
                continue
            if lowered == "unseen":
                criteria.append("UNSEEN")
                continue
            if ":" in term:
                key, value = term.split(":", 1)
                value = value.strip()
                if not value:
                    continue
                key = key.lower().strip()
                if key == "from":
                    criteria.extend(["FROM", f'"{value}"'])
                    continue
                if key == "to":
                    criteria.extend(["TO", f'"{value}"'])
                    continue
                if key == "subject":
                    criteria.extend(["SUBJECT", f'"{value}"'])
                    continue
                if key == "since":
                    criteria.extend(["SINCE", value])
                    continue
                if key == "before":
                    criteria.extend(["BEFORE", value])
                    continue
            criteria.extend(["TEXT", f'"{term}"'])
        return criteria or ["ALL"]

    def search(self, query: str, limit: int = 10, account: str = "", folder: str = "") -> dict:
        _ = account
        box = folder or self.inbox_folder
        client = self._imap()
        try:
            typ, data = client.select(box)
            if typ != "OK":
                return {"error": f"email search failed: cannot select folder {box}"}
            typ, data = client.uid("SEARCH", None, *self._criteria(query))
            if typ != "OK":
                return {"error": "email search failed: search rejected"}
            uids = [item for item in (data[0] or b"").decode("utf-8", "ignore").split() if item]
            selected = list(reversed(uids))[: max(1, int(limit))]
            messages: list[dict] = []
            for uid in selected:
                typ, fetch_data = client.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])")
                if typ != "OK" or not fetch_data:
                    continue
                raw = b""
                for item in fetch_data:
                    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
                        raw += bytes(item[1])
                parsed = BytesParser(policy=default).parsebytes(raw)
                messages.append(
                    {
                        "id": uid,
                        "subject": str(parsed.get("Subject", "")),
                        "from": str(parsed.get("From", "")),
                        "to": str(parsed.get("To", "")),
                        "date": str(parsed.get("Date", "")),
                        "folder": box,
                    }
                )
            return {"messages": messages}
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def read(self, message_id: str, account: str = "", folder: str = "") -> dict:
        _ = account
        box = folder or self.inbox_folder
        client = self._imap()
        try:
            typ, data = client.select(box)
            if typ != "OK":
                return {"error": f"email read failed: cannot select folder {box}"}
            typ, fetch_data = client.uid("FETCH", str(message_id), "(RFC822)")
            if typ != "OK" or not fetch_data:
                return {"error": f"email read failed: unknown message id {message_id}"}
            raw = b""
            for item in fetch_data:
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (bytes, bytearray)):
                    raw += bytes(item[1])
            if not raw:
                return {"error": f"email read failed: unknown message id {message_id}"}
            parsed = message_from_bytes(raw, policy=default)
            text = parsed.as_string()
            return {"id": str(message_id), "body": text, "folder": box}
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        account: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        _ = account
        msg = EmailMessage()
        msg["From"] = self.email
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg.set_content(body)
        recipients = [addr for addr in [*to, *(cc or []), *(bcc or [])] if addr]
        client = self._smtp()
        try:
            client.send_message(msg, from_addr=self.email, to_addrs=recipients)
            return {"ok": True}
        finally:
            try:
                client.quit()
            except Exception:
                pass

    def draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        account: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        _ = account
        lines = [f"From: {self.email}", f"To: {', '.join(to)}", f"Subject: {subject}"]
        if cc:
            lines.append(f"Cc: {', '.join(cc)}")
        if bcc:
            lines.append(f"Bcc: {', '.join(bcc)}")
        lines += ["", body]
        draft_id = str(uuid.uuid4())
        draft_dir = os.path.join(tempfile.gettempdir(), "hydrai-toolbox-email-drafts")
        os.makedirs(draft_dir, exist_ok=True)
        draft_path = os.path.join(draft_dir, f"{draft_id}.eml")
        with open(draft_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        return {"ok": True, "draft_id": draft_id, "path": draft_path}


@dataclass
class GmailOAuthEmailProvider:
    email: str
    credentials_path: str
    token_path: str
    scopes: tuple[str, ...]
    timeout: int = 60

    def _deps(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("gmail_oauth dependencies are not installed") from exc
        return Request, Credentials, build

    def _credentials(self):
        Request, Credentials, _ = self._deps()
        if not os.path.isfile(self.token_path):
            raise RuntimeError(f"gmail_oauth token file not found: {self.token_path}")
        creds = Credentials.from_authorized_user_file(self.token_path, list(self.scopes))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(self.token_path, "w", encoding="utf-8") as handle:
                handle.write(creds.to_json())
        if not creds.valid:
            raise RuntimeError("gmail_oauth credentials are invalid; run gmail-auth first")
        return creds

    def _service(self):
        _, _, build = self._deps()
        return build("gmail", "v1", credentials=self._credentials(), cache_discovery=False)

    def search(self, query: str, limit: int = 10, account: str = "", folder: str = "") -> dict:
        _ = account
        service = self._service()
        labels = [folder] if folder else None
        resp = service.users().messages().list(userId="me", q=str(query or ""), maxResults=max(1, int(limit)), labelIds=labels).execute()
        messages = []
        for item in resp.get("messages", []) or []:
            detail = service.users().messages().get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
            headers = {h.get("name", ""): h.get("value", "") for h in detail.get("payload", {}).get("headers", [])}
            messages.append(
                {
                    "id": item["id"],
                    "subject": headers.get("Subject", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "date": headers.get("Date", ""),
                    "folder": folder or "INBOX",
                }
            )
        return {"messages": messages}

    def read(self, message_id: str, account: str = "", folder: str = "") -> dict:
        _ = account, folder
        service = self._service()
        detail = service.users().messages().get(userId="me", id=str(message_id), format="raw").execute()
        raw = detail.get("raw", "")
        body = base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8", "replace") if raw else ""
        return {"id": str(message_id), "body": body}

    def _encode_message(self, to: list[str], subject: str, body: str, cc: list[str] | None = None, bcc: list[str] | None = None) -> str:
        msg = EmailMessage()
        msg["From"] = self.email
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg.set_content(body)
        return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        account: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        _ = account
        service = self._service()
        raw = self._encode_message(to, subject, body, cc=cc, bcc=bcc)
        result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "id": result.get("id", "")}

    def draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        account: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        _ = account
        service = self._service()
        raw = self._encode_message(to, subject, body, cc=cc, bcc=bcc)
        result = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return {"ok": True, "draft_id": result.get("id", "")}
