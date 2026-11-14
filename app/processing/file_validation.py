import io
import zipfile
from pathlib import Path


class ResumeValidationError(ValueError):
    pass


def validate_resume_bytes(filename: str, data: bytes, max_bytes: int) -> str:
    if not filename or not data:
        raise ResumeValidationError("Choose a non-empty PDF or DOCX resume.")
    if len(data) > max_bytes:
        raise ResumeValidationError(f"Resume must be no larger than {max_bytes // (1024 * 1024)} MB.")

    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ResumeValidationError("The uploaded file is not a valid PDF.")
        return "pdf"

    if extension == ".docx":
        if not data.startswith(b"PK"):
            raise ResumeValidationError("The uploaded file is not a valid DOCX document.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ResumeValidationError("The uploaded file is not a valid DOCX document.")
                if len(names) > 2000 or sum(entry.file_size for entry in archive.infolist()) > 30 * 1024 * 1024:
                    raise ResumeValidationError("The DOCX document expands beyond the permitted size.")
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as error:
            raise ResumeValidationError("The uploaded file is not a valid DOCX document.") from error
        return "docx"

    raise ResumeValidationError("Only PDF and DOCX resumes are supported.")
