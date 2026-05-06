from __future__ import annotations
import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

def is_colab() -> bool:
    try:
        import google.colab
        return True
    except ImportError:
        return False

def is_ci() -> bool:
    return os.environ.get("CI", "false").lower() == "true"

def get_credentials():
    if is_colab():
        from google.colab import auth
        from google.auth import default
        auth.authenticate_user()
        creds, _ = default(scopes=SCOPES)
        return creds
    sa_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
    if not sa_json:
        raise EnvironmentError("GDRIVE_SERVICE_ACCOUNT env var not set.")
    from google.oauth2 import service_account
    info = json.loads(sa_json)
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

def get_gspread_client():
    import gspread
    return gspread.authorize(get_credentials())


def _get_or_create_folder(service, name: str,
                           parent_id: str | None = None) -> str:
    """Return Drive folder ID, creating it if it doesn't exist."""
    q_parts = [
        f"name='{name}'",
        "mimeType='application/vnd.google-apps.folder'",
        "trashed=false",
    ]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    res = service.files().list(
        q=" and ".join(q_parts), fields="files(id)"
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    f = service.files().create(body=meta, fields="id").execute()
    return f["id"]


def build_drive_service():
    """Return an authenticated Google Drive API service object."""
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=get_credentials(),
                 cache_discovery=False)


def upload_to_drive(local_path, drive_folder_name: str) -> str:
    from googleapiclient.http import MediaFileUpload
    from pathlib import Path
    local_path = Path(local_path)
    service = build_drive_service()
    folder_id = _get_or_create_folder(service, drive_folder_name)
    q = (f"name=\'{local_path.name}\' and \'{folder_id}\' in parents "
         f"and trashed=false")
    if service.files().list(q=q, fields="files(id)").execute().get("files"):
        print(f"  Already on Drive, skipping: {local_path.name}")
        return ""
    print(f"  Uploading to Drive: {local_path.name}", end=" ", flush=True)
    media = MediaFileUpload(str(local_path), mimetype="video/mp4", resumable=True)
    uploaded = service.files().create(
        body={"name": local_path.name, "parents": [folder_id]},
        media_body=media,
        fields="id",
    ).execute()
    fid = uploaded["id"]
    print(f"done (id={fid})")
    return fid
