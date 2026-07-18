"""
Email processor — extracts text and metadata from email archives.

Supports:
  * .eml  (RFC-822) via the Python standard library
  * .msg  (Outlook) via the optional `extract-msg` package

Emails are a first-class industrial document type (approvals, incident
threads, vendor correspondence). We surface the headers (From/To/Subject/
Date) into the text so PERSONNEL and DATE entities extract cleanly, then
append the plain-text body.
"""

import os
from email import policy
from email.parser import BytesParser

from app.ingestion.canonical_document import CanonicalDocument


class EmailProcessor:
    def process(self, file_path: str) -> CanonicalDocument:
        print(f"Processing Email: {file_path}")
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".msg":
                return self._process_msg(file_path)
            return self._process_eml(file_path)
        except Exception as e:
            print(f"  Email processing failed for {file_path}: {e}")
            return CanonicalDocument(
                file_path=file_path,
                file_type="email",
                text=f"[Could not parse email: {e}]",
                metadata={"processor": "email", "error": str(e)},
            )

    # ------------------------------------------------------------------
    # .eml — standard library
    # ------------------------------------------------------------------
    def _process_eml(self, file_path: str) -> CanonicalDocument:
        with open(file_path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)

        headers = {
            "From": msg.get("From", ""),
            "To": msg.get("To", ""),
            "Cc": msg.get("Cc", ""),
            "Subject": msg.get("Subject", ""),
            "Date": msg.get("Date", ""),
        }

        # Prefer the plain-text part; fall back to stripped HTML.
        body = ""
        try:
            part = msg.get_body(preferencelist=("plain", "html"))
            if part is not None:
                content = part.get_content()
                if part.get_content_subtype() == "html":
                    body = self._strip_html(content)
                else:
                    body = content
        except Exception:
            body = ""

        attachments = [
            att.get_filename()
            for att in msg.iter_attachments()
            if att.get_filename()
        ]

        return self._build_doc(file_path, headers, body, attachments, "eml")

    # ------------------------------------------------------------------
    # .msg — optional extract-msg dependency
    # ------------------------------------------------------------------
    def _process_msg(self, file_path: str) -> CanonicalDocument:
        try:
            import extract_msg
        except ImportError:
            raise RuntimeError(
                "Reading .msg files requires the 'extract-msg' package "
                "(pip install extract-msg)."
            )

        m = extract_msg.Message(file_path)
        headers = {
            "From": m.sender or "",
            "To": m.to or "",
            "Cc": m.cc or "",
            "Subject": m.subject or "",
            "Date": str(m.date or ""),
        }
        body = m.body or ""
        attachments = [
            a.longFilename or a.shortFilename
            for a in getattr(m, "attachments", [])
            if (a.longFilename or a.shortFilename)
        ]
        m.close()
        return self._build_doc(file_path, headers, body, attachments, "msg")

    # ------------------------------------------------------------------
    # Shared assembly
    # ------------------------------------------------------------------
    @staticmethod
    def _build_doc(file_path, headers, body, attachments, source_fmt) -> CanonicalDocument:
        lines = []
        for key, value in headers.items():
            if value:
                lines.append(f"{key}: {value}")
        if attachments:
            lines.append(f"Attachments: {', '.join(attachments)}")
        header_block = "\n".join(lines)

        text = f"{header_block}\n\n{(body or '').strip()}".strip()

        return CanonicalDocument(
            file_path=file_path,
            file_type="email",
            text=text,
            metadata={
                "processor": f"email:{source_fmt}",
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "attachments": attachments,
            },
        )

    @staticmethod
    def _strip_html(html: str) -> str:
        """Very small HTML-to-text fallback (no external dependency)."""
        import re
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
