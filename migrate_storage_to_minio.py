"""
One-off: uploads every file under ./storage into the MinIO bucket under the
same relative-path key. db.py's storage_key format (<task_id>/<hash>_<name>)
is unchanged by the move to MinIO, so existing `files.storage_key` rows --
written back when uploads were local-disk-only -- keep resolving once their
bytes are here too.

Run once, after `docker compose up minio` (or with the MINIO_* env vars
below pointed at wherever else you're serving it). The local ./storage
directory can be deleted afterwards; nothing else reads from it.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from minio import Minio

load_dotenv()

STORAGE_DIR = Path(__file__).parent / "storage"

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "gryzun")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"


def main():
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)

    uploaded = 0
    for path in sorted(STORAGE_DIR.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        storage_key = str(path.relative_to(STORAGE_DIR))
        client.fput_object(MINIO_BUCKET, storage_key, str(path))
        print(f"uploaded {storage_key}")
        uploaded += 1

    print(f"Done: {uploaded} file(s) uploaded to bucket {MINIO_BUCKET!r}.")


if __name__ == "__main__":
    main()
