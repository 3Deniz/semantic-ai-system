"""PDF text extraction helpers with per-page outputs.

This module is Phase-1 infrastructure for PDF ingestion:
- Validate incoming PDF bytes and size limits.
- Extract text page by page.
- Normalize noisy PDF text into parser-friendly content.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - handled at runtime when dependency is absent
    PdfReader = None


class PDFIngestionError(Exception):
    """Raised when a PDF cannot be extracted safely."""


@dataclass(frozen=True)
class PDFIngestionConfig:
    max_file_size_bytes: int = 20 * 1024 * 1024  # 20 MB


class PDFIngestion:
    def __init__(self, config: PDFIngestionConfig | None = None):
        self.config = config or PDFIngestionConfig()

    def extract_pages_from_bytes(self, data: bytes) -> list[dict]:
        """Return normalized text page-by-page.

        Output format:
            [{"page_index": 0, "text": "..."}, ...]
        """
        if not data:
            raise PDFIngestionError("Empty PDF payload.")

        if len(data) > self.config.max_file_size_bytes:
            raise PDFIngestionError("PDF exceeds configured size limit.")

        if PdfReader is None:
            raise PDFIngestionError("pypdf is not installed.")

        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:
            raise PDFIngestionError("Invalid or corrupted PDF.") from exc

        if getattr(reader, "is_encrypted", False):
            raise PDFIngestionError("Encrypted PDF is not supported.")

        pages = []
        for page_index, page in enumerate(reader.pages):
            try:
                raw_text = page.extract_text() or ""
            except Exception as exc:
                raise PDFIngestionError(f"Failed to extract text from page {page_index}.") from exc

            normalized = normalize_pdf_text(raw_text)
            pages.append({"page_index": page_index, "text": normalized})

        if not pages:
            raise PDFIngestionError("PDF has no readable pages.")

        if not any(p["text"] for p in pages):
            raise PDFIngestionError("PDF has no extractable text.")

        return pages

    def extract_pages_from_file(self, path: str) -> list[dict]:
        with open(path, "rb") as f:
            return self.extract_pages_from_bytes(f.read())


def normalize_pdf_text(text: str) -> str:
    """Normalize noisy PDF text for downstream sentence parsing."""
    if not text:
        return ""

    # Remove soft hyphen and de-hyphenate line-break splits (e.g. seman-\ntic).
    text = text.replace("\u00ad", "")
    text = re.sub(r"([A-Za-z0-9])\-\n([A-Za-z0-9])", r"\1\2", text)

    # Normalize line endings first.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Keep paragraph boundaries but clean dense whitespace noise.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Trim spaces around line boundaries.
    text = "\n".join(line.strip() for line in text.split("\n"))

    return text.strip()
