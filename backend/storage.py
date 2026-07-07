"""
storage.py
==========
Object storage abstraction for Phase 1.

WHY THIS EXISTS: Railway/Render containers don't guarantee persistent disk
across redeploys/restarts (the same ephemeral-disk problem Phase 0 had with
Streamlit Cloud's jobs/ folder, just at a different layer). Job metadata
lives in Postgres, but the actual file BYTES (uploaded input, checkpoint
CSV, final output Excel) need somewhere durable to live. This module gives
tasks.py/main.py a single save/load/exists interface, backed by either:

  - LocalStorage: plain files under STORAGE_LOCAL_DIR. Fine for local dev
    and for this sandbox's testing - NOT durable on Railway/Render.
  - S3Storage: any S3-compatible object store (AWS S3, Cloudflare R2,
    Backblaze B2, Supabase Storage's S3-compatible endpoint, etc). Set
    STORAGE_BACKEND=s3 and the S3_* env vars to switch to this in
    production; nothing else in the codebase needs to change.

Choosing which backend is active is a single env var (STORAGE_BACKEND),
read once at import time, so tasks.py/main.py just call `storage.save(...)`
/`storage.load(...)` without caring which one is active.
"""
import io
import os
from pathlib import Path

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()


class LocalStorage:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or os.environ.get("STORAGE_LOCAL_DIR", "./storage_data"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> None:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        path = self.base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"storage key not found: {key}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return (self.base_dir / key).exists()

    def delete(self, key: str) -> None:
        path = self.base_dir / key
        if path.exists():
            path.unlink()


class S3Storage:
    """Works against AWS S3 or any S3-compatible endpoint (Cloudflare R2,
    Backblaze B2, Supabase Storage) by pointing S3_ENDPOINT_URL at it."""

    def __init__(self):
        import boto3
        self.bucket = os.environ["S3_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL"),  # None -> real AWS S3
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("S3_REGION", "auto"),
        )

    def save(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def load(self, key: str) -> bytes:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey:
            raise FileNotFoundError(f"storage key not found: {key}")
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def _make_backend():
    if STORAGE_BACKEND == "s3":
        return S3Storage()
    return LocalStorage()


_backend = _make_backend()


def save(key: str, data: bytes) -> None:
    _backend.save(key, data)


def load(key: str) -> bytes:
    return _backend.load(key)


def exists(key: str) -> bool:
    return _backend.exists(key)


def delete(key: str) -> None:
    _backend.delete(key)


def save_dataframe_excel(key: str, df) -> None:
    """Convenience: write a DataFrame to an in-memory .xlsx and store it,
    without ever touching local disk for the intermediate file."""
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    save(key, buf.getvalue())


def load_dataframe_excel(key: str):
    import pandas as pd
    return pd.read_excel(io.BytesIO(load(key)))


def save_dataframe_csv(key: str, df) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    save(key, buf.getvalue())


def load_dataframe_csv(key: str, **kwargs):
    import pandas as pd
    return pd.read_csv(io.BytesIO(load(key)), **kwargs)
