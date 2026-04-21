"""
Google Drive Storage — завантажує файли в AI_Lab_Archive.

Env vars:
  GOOGLE_CREDENTIALS_JSON — сервісний акаунт (той самий що для Sheets)
  GDRIVE_ARCHIVE_FOLDER_ID — ID кореневої папки AI_Lab_Archive у Drive
"""

import io
import json
import os

from core.logger import get_logger

logger = get_logger(__name__)

_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
_ROOT_FOLDER_ID = os.getenv("GDRIVE_ARCHIVE_FOLDER_ID", "")
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_folder_cache: dict[str, str] = {}
_drive_service = None


def _get_service():
    global _drive_service
    if _drive_service is not None:
        return _drive_service
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    if not _CREDENTIALS_JSON:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON не задано")
    if not _ROOT_FOLDER_ID:
        raise RuntimeError("GDRIVE_ARCHIVE_FOLDER_ID не задано")

    creds = Credentials.from_service_account_info(
        json.loads(_CREDENTIALS_JSON),
        scopes=_DRIVE_SCOPES,
    )
    _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _drive_service


def _ensure_folder(path_key: str, parent_id: str, name: str) -> str:
    """Знаходить або створює підпапку name у parent_id. Результат кешується."""
    if path_key in _folder_cache:
        return _folder_cache[path_key]

    svc = _get_service()
    q = (
        f"name='{name}' and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files", [])
    if files:
        folder_id = files[0]["id"]
    else:
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = svc.files().create(body=meta, fields="id").execute()
        folder_id = folder["id"]

    _folder_cache[path_key] = folder_id
    return folder_id


def upload_file(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    client_id: str,
    subfolder: str = "analysis",
) -> dict:
    """Завантажує файл у /AI_Lab_Archive/{client_id}/{subfolder}/.

    Returns: {"file_id": str, "web_view_link": str}
    """
    if not _ROOT_FOLDER_ID or not _CREDENTIALS_JSON:
        logger.warning("GDrive не налаштовано — пропускаємо upload '%s'", filename)
        return {"file_id": "", "web_view_link": ""}

    try:
        svc = _get_service()
        from googleapiclient.http import MediaIoBaseUpload

        client_folder_id = _ensure_folder(client_id, _ROOT_FOLDER_ID, client_id)
        sub_folder_id = _ensure_folder(
            f"{client_id}/{subfolder}", client_folder_id, subfolder
        )

        file_meta = {"name": filename, "parents": [sub_folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
        uploaded = svc.files().create(
            body=file_meta, media_body=media, fields="id,webViewLink"
        ).execute()

        # Дозволяємо перегляд для всіх хто має посилання
        svc.permissions().create(
            fileId=uploaded["id"],
            body={"type": "anyone", "role": "reader"},
        ).execute()

        logger.info("GDrive upload OK: %s → %s", filename, uploaded.get("webViewLink"))
        return {"file_id": uploaded["id"], "web_view_link": uploaded.get("webViewLink", "")}

    except Exception as e:
        logger.error("GDrive upload помилка (%s): %s", filename, e)
        return {"file_id": "", "web_view_link": ""}


def delete_file(file_id: str) -> bool:
    """Видаляє файл з GDrive."""
    if not file_id:
        return False
    try:
        _get_service().files().delete(fileId=file_id).execute()
        logger.info("GDrive delete OK: %s", file_id)
        return True
    except Exception as e:
        logger.error("GDrive delete помилка (%s): %s", file_id, e)
        return False
