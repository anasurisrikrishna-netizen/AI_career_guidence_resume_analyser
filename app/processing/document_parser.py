from io import BytesIO
import zipfile

import fitz
from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from app.processing.file_validation import ResumeValidationError


class ResumeProcessingError(RuntimeError):
    pass


def extract_resume_text(data: bytes, file_type: str, max_pages: int = 80, max_characters: int = 50000) -> str:
    if file_type == "pdf":
        try:
            with fitz.open(stream=data, filetype="pdf") as document:
                if document.needs_pass:
                    raise ResumeValidationError("Password-protected PDF resumes are not supported.")
                if len(document) > max_pages:
                    raise ResumeValidationError(f"Resume must not exceed {max_pages} pages.")
                text = "\n".join(page.get_text("text", sort=True) for page in document)
        except ResumeValidationError:
            raise
        except (fitz.FileDataError, RuntimeError, ValueError) as error:
            raise ResumeProcessingError("The PDF could not be read.") from error
    elif file_type == "docx":
        try:
            document = Document(BytesIO(data))
        except (
            PackageNotFoundError,
            zipfile.BadZipFile,
            KeyError,
            ValueError,
            OSError,
            RuntimeError,
            NotImplementedError,
        ) as error:
            raise ResumeProcessingError("The DOCX document could not be read.") from error

        parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        text = "\n".join(parts)
    else:
        raise ResumeValidationError("Unsupported resume file type.")

    text = text.strip()
    if not text:
        raise ResumeValidationError("No readable text was found in the resume.")
    if len(text) > max_characters:
        raise ResumeValidationError(
            f"Extracted resume text is too long to analyze. Keep it under {max_characters} characters."
        )
    return text
