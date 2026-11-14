from io import BytesIO

import fitz
import pytest
from docx import Document

from app.processing.document_parser import extract_resume_text
from app.processing.file_validation import ResumeValidationError, validate_resume_bytes


def _pdf_bytes():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Jordan Example\nPython Developer")
    data = document.tobytes()
    document.close()
    return data


def _docx_bytes():
    document = Document()
    document.add_paragraph("Jordan Example")
    document.add_paragraph("Python Developer")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "data", "file_type", "expected"),
    [
        ("resume.pdf", _pdf_bytes(), "pdf", "Python Developer"),
        ("resume.docx", _docx_bytes(), "docx", "Python Developer"),
    ],
    ids=["pdf", "docx"],
)
def test_extracts_supported_document_text(filename, data, file_type, expected):
    assert validate_resume_bytes(filename, data, 5 * 1024 * 1024) == file_type
    assert expected in extract_resume_text(data, file_type)


def test_rejects_mismatched_and_oversized_uploads():
    with pytest.raises(ResumeValidationError):
        validate_resume_bytes("resume.pdf", b"not a pdf", 100)

    with pytest.raises(ResumeValidationError):
        validate_resume_bytes("resume.docx", b"%PDF-1.7", 100)

    with pytest.raises(ResumeValidationError):
        validate_resume_bytes("resume.pdf", b"%PDF-" + b"x" * 100, 10)


def test_rejects_empty_or_unreadable_document_text():
    document = fitz.open()
    document.new_page()
    data = document.tobytes()
    document.close()

    with pytest.raises(ResumeValidationError):
        extract_resume_text(data, "pdf")
