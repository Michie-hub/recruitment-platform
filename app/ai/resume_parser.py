"""
Resume text extraction.

Known limitation: only PDF extraction is implemented. DOC/DOCX files can
still be uploaded and stored (Milestone 3), but won't be indexed for
semantic search until DOCX extraction is added — flagged here rather than
silently failing without explanation.
"""

import io

from pypdf import PdfReader


class UnsupportedResumeFormatError(Exception):
    """Raised when text extraction isn't implemented for the given content type."""


def extract_text(file_bytes: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        return _extract_pdf_text(file_bytes)
    raise UnsupportedResumeFormatError(
        f"Text extraction not yet implemented for {content_type}."
    )


def _extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages_text).strip()
