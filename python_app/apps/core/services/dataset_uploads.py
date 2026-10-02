"""Private storage helpers for researcher-uploaded source datasets."""

import hashlib
import os
import uuid
from pathlib import PurePosixPath

from django.core.files.storage import default_storage


def store_dataset_upload(upload, owner_id: int) -> dict[str, int | str]:
    """Store an uploaded file under a non-public, owner-scoped random key."""
    extension = PurePosixPath(upload.name.replace("\\", "/")).suffix.lower()
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)

    requested_key = f"research-datasets/{owner_id}/{uuid.uuid4().hex}{extension}"
    storage_key = default_storage.save(requested_key, upload)
    original_filename = os.path.basename(upload.name.replace("\\", "/"))[:255]
    return {
        "storage_key": storage_key,
        "original_filename": original_filename,
        "content_sha256": digest.hexdigest(),
        "byte_size": upload.size,
    }
