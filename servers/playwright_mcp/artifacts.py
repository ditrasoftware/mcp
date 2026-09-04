from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from .settings import Settings


class ArtifactStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._bucket = None
        self._credentials = None
        if settings.gcs_bucket:
            from google.cloud import storage

            client = storage.Client(project=settings.gcp_project)
            self._credentials = client._credentials
            self._bucket = client.bucket(settings.gcs_bucket)
        self.local_root = Path("/tmp/playwright-mcp-artifacts")

    def _object_key(self, tenant_id: str, user_id: str, artifact_id: str, digest: str, extension: str) -> str:
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        return f"{self.settings.artifact_prefix}/tenants/{tenant_id}/users/{user_id}/{today}/{artifact_id}-{digest[:20]}.{extension}"

    def _manifest_key(self, tenant_id: str, user_id: str, artifact_id: str) -> str:
        return f"{self.settings.artifact_prefix}/tenants/{tenant_id}/users/{user_id}/manifests/{artifact_id}.json"

    async def _signed_url(self, blob: Any) -> str:
        access_token = None
        if self._credentials is not None and not hasattr(self._credentials, "sign_bytes"):
            from google.auth.transport.requests import Request

            def refresh() -> str:
                if not self._credentials.valid:
                    self._credentials.refresh(Request())
                return str(self._credentials.token)

            access_token = await asyncio.to_thread(refresh)
        return await asyncio.to_thread(
            blob.generate_signed_url,
            version="v4",
            expiration=timedelta(seconds=self.settings.signed_url_ttl_seconds),
            method="GET",
            response_disposition="inline",
            service_account_email=self.settings.gcp_service_account,
            access_token=access_token,
        )

    async def put(
        self,
        tenant_id: str,
        user_id: str,
        container_id: str,
        content: bytes,
        content_type: str,
        extension: str,
        retention_mode: str,
    ) -> dict[str, Any]:
        if retention_mode not in {"short", "durable"}:
            raise ValueError("retention_mode must be 'short' or 'durable'")
        if len(content) > self.settings.max_artifact_bytes:
            raise ValueError(f"Artifact exceeds {self.settings.max_artifact_bytes} byte limit")
        artifact_id = f"art_{uuid.uuid4().hex}"
        digest = hashlib.sha256(content).hexdigest()
        key = self._object_key(tenant_id, user_id, artifact_id, digest, extension)
        metadata = {
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "container_id": container_id,
            "object_name": key,
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": digest,
            "retention_mode": retention_mode,
        }
        if self._bucket is not None:
            blob = self._bucket.blob(key)
            await asyncio.to_thread(blob.upload_from_string, content, content_type=content_type)
            if retention_mode == "durable":
                manifest = self._bucket.blob(self._manifest_key(tenant_id, user_id, artifact_id))
                await asyncio.to_thread(manifest.upload_from_string, json.dumps(metadata), content_type="application/json")
            url = await self._signed_url(blob)
        else:
            path = self.local_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            if retention_mode == "durable":
                manifest_path = self.local_root / self._manifest_key(tenant_id, user_id, artifact_id)
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(metadata), encoding="utf-8")
            url = None
        result = dict(metadata)
        result.update({"signed_url": url, "signed_url_expires_in_seconds": self.settings.signed_url_ttl_seconds if url else None, "storage": "gcs" if self._bucket is not None else "local"})
        if retention_mode == "short":
            result["retention_days"] = self.settings.short_retention_days
        return result

    async def refresh_url(self, tenant_id: str, user_id: str, artifact_id: str) -> dict[str, Any]:
        if not artifact_id.startswith("art_") or len(artifact_id) != 36:
            raise ValueError("Invalid artifact ID")
        manifest_key = self._manifest_key(tenant_id, user_id, artifact_id)
        if self._bucket is not None:
            manifest = self._bucket.blob(manifest_key)
            try:
                metadata = json.loads(await asyncio.to_thread(manifest.download_as_text))
            except Exception as exc:
                raise ValueError("Durable artifact not found") from exc
            if metadata.get("tenant_id") != tenant_id or metadata.get("user_id") != user_id or metadata.get("artifact_id") != artifact_id:
                raise ValueError("Artifact tenant ownership mismatch")
            blob = self._bucket.blob(metadata["object_name"])
            metadata["signed_url"] = await self._signed_url(blob)
        else:
            path = self.local_root / manifest_key
            if not path.is_file():
                raise ValueError("Durable artifact not found")
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata["signed_url"] = None
        metadata["signed_url_expires_in_seconds"] = self.settings.signed_url_ttl_seconds if metadata.get("signed_url") else None
        metadata["storage"] = "gcs" if self._bucket is not None else "local"
        return metadata


def content_metadata(artifact_type: str) -> tuple[str, str]:
    values = {
        "screenshot": ("image/png", "png"),
        "jpeg": ("image/jpeg", "jpg"),
        "pdf": ("application/pdf", "pdf"),
        "html": ("text/html; charset=utf-8", "html"),
    }
    if artifact_type not in values:
        raise ValueError(f"Unsupported artifact type: {artifact_type}")
    return values[artifact_type]
