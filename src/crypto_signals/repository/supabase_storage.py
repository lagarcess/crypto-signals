"""
Supabase Storage Repository.

Handles interactions with Supabase Storage buckets for Parquet file caching.
"""

from pathlib import Path
from typing import Optional

from loguru import logger
from supabase import Client, create_client

from crypto_signals.config import get_settings


class SupabaseStorageRepository:
    """
    Repository for managing Supabase Storage operations.
    """

    def __init__(self, bucket_name: str):
        """
        Initialize with Supabase client and target bucket.

        Args:
            bucket_name: Name of the bucket to interact with.
        """
        settings = get_settings()
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            self.client: Optional[Client] = None
            logger.warning("Supabase credentials missing. Storage operations will be disabled.")
        else:
            self.client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY.get_secret_value()
            )

        self.bucket_name = bucket_name

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        """
        Upload a local file to Supabase Storage.

        Args:
            local_path: Path to the local file.
            remote_path: Target path in the bucket.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.client:
            return False

        try:
            with open(local_path, "rb") as f:
                self.client.storage.from_(self.bucket_name).upload(
                    path=remote_path,
                    file=f,
                    file_options={"content-type": "application/octet-stream", "x-upsert": "true"}
                )
            logger.info(f"Uploaded {local_path} to {self.bucket_name}/{remote_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {local_path} to Supabase: {e}")
            return False

    def download_file(self, remote_path: str, local_path: Path) -> bool:
        """
        Download a file from Supabase Storage.

        Args:
            remote_path: Path in the bucket.
            local_path: Local path to save the file.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.client:
            return False

        try:
            res = self.client.storage.from_(self.bucket_name).download(remote_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(res)
            logger.info(f"Downloaded {self.bucket_name}/{remote_path} to {local_path}")
            return True
        except Exception as e:
            logger.debug(f"File not found or failed to download from Supabase: {remote_path} | {e}")
            return False

    def file_exists(self, remote_path: str) -> bool:
        """
        Check if a file exists in the bucket.

        Args:
            remote_path: Path in the bucket.

        Returns:
            bool: True if exists, False otherwise.
        """
        if not self.client:
            return False

        try:
            # list() returns a list of files in the directory
            path_parts = remote_path.rsplit("/", 1)
            folder = path_parts[0] if len(path_parts) > 1 else ""
            filename = path_parts[-1]

            files = self.client.storage.from_(self.bucket_name).list(folder)
            return any(f['name'] == filename for f in files)
        except Exception as e:
            logger.error(f"Error checking file existence in Supabase: {e}")
            return False

    def create_bucket_if_not_exists(self) -> bool:
        """
        Ensure the target bucket exists.

        Returns:
            bool: True if bucket exists or was created, False otherwise.
        """
        if not self.client:
            return False

        try:
            buckets = self.client.storage.list_buckets()
            if any(b.name == self.bucket_name for b in buckets):
                return True

            self.client.storage.create_bucket(self.bucket_name, options={"public": False})
            logger.info(f"Created Supabase bucket: {self.bucket_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create Supabase bucket {self.bucket_name}: {e}")
            return False
