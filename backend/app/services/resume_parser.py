"""
Resume text extraction for PDF and DOCX.

Deliberately boring, deterministic code: if a file cannot be parsed we raise
a typed error so the API can say exactly what went wrong instead of storing
an empty profile.
"""
import io
import re

from docx import Document
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class ResumeParseError(Exception):
    """Raised when a resume file cannot be turned into text."""


def extract_text(data: bytes, file_type: str, max_pages: int = 20) -> str:
    if file_type == "pdf":
        return _extract_pdf(data, max_pages)
    if file_type == "docx":
        return _extract_docx(data)
    raise ResumeParseError(f"Unsupported file type: {file_type}")


def _extract_pdf(data: bytes, max_pages: int) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, ValueError, OSError) as exc:
        raise ResumeParseError("This PDF could not be read. It may be corrupted.") from exc

    if reader.is_encrypted:
        try:
            if reader.decrypt("") == 0:
                raise ResumeParseError("This PDF is password-protected. Re-export it without a password.")
        except Exception as exc:  # pypdf raises several crypto errors
            raise ResumeParseError("This PDF is password-protected. Re-export it without a password.") from exc

    pages = reader.pages[:max_pages]
    chunks: list[str] = []
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            # One unreadable page should not discard the rest of the resume.
            chunks.append("")
    text = "\n".join(chunks)
    if not text.strip():
        raise ResumeParseError(
            "No selectable text was found in this PDF. If it is a scanned image, "
            "export a text-based PDF or a DOCX instead."
        )
    return normalize_text(text)


def _extract_docx(data: bytes) -> str:
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise ResumeParseError("This DOCX could not be read. It may be corrupted.") from exc

    parts: list[str] = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    if not text.strip():
        raise ResumeParseError("This DOCX contains no readable text.")
    return normalize_text(text)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
