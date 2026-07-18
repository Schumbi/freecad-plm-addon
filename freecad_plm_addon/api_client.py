import json
import re
from pathlib import Path
from urllib import error, parse, request

from .errors import (
    APIError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from .workspace import sha256_file


class PLMClient:
    def __init__(self, base_url, api_token, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token.strip()
        self.timeout = timeout

    def get_projects(self):
        return self._json("GET", "/api/projects/")["projects"]

    def get_project(self, project_id):
        return self._json("GET", f"/api/projects/{project_id}/")["project"]

    def update_project(self, project_id, data):
        return self._json("POST", f"/api/projects/{project_id}/", data)["project"]

    def import_project(self, zip_path, project_data, snapshot_name):
        fields = dict(project_data)
        fields["snapshot_name"] = snapshot_name
        return self._multipart(
            "/api/projects/import/",
            fields,
            "file",
            Path(zip_path),
            "application/zip",
        )

    def import_project_snapshot(self, project_id, zip_path, snapshot_name):
        return self._multipart(
            f"/api/projects/{project_id}/snapshots/import/",
            {"name": snapshot_name},
            "file",
            Path(zip_path),
            "application/zip",
        )

    def get_parts(self, project_id):
        return self._json("GET", f"/api/projects/{project_id}/parts/")["parts"]

    def create_part(self, project_id, data):
        return self._json("POST", f"/api/projects/{project_id}/parts/", data)["part"]

    def get_part(self, part_id):
        return self._json("GET", f"/api/parts/{part_id}/")

    def update_part(self, part_id, data):
        return self._json("POST", f"/api/parts/{part_id}/", data)["part"]

    def get_revision(self, revision_id):
        return self._json("GET", f"/api/revisions/{revision_id}/")["revision"]

    def update_revision_notes(self, revision_id, notes):
        return self._json(
            "POST",
            f"/api/revisions/{revision_id}/notes/",
            {"notes": notes},
        )["revision"]

    def get_revision_manifest(self, revision_id, snapshot_id=None):
        path = f"/api/revisions/{revision_id}/manifest/"
        if snapshot_id is not None:
            path = f"{path}?{parse.urlencode({'snapshot_id': snapshot_id})}"
        return self._json("GET", path)["manifest"]

    def download_revision_file(self, download_url, target_path, expected_sha256):
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and sha256_file(target_path) == expected_sha256:
            return
        response = self._open("GET", download_url, absolute=True)
        target_path.write_bytes(response.read())
        digest = sha256_file(target_path)
        if digest != expected_sha256:
            target_path.unlink(missing_ok=True)
            raise APIError(0, f"SHA-256 stimmt nicht: {target_path}")

    def checkout_revision(self, revision_id, snapshot_id=None, workspace_hint=""):
        payload = {"workspace_hint": workspace_hint}
        if snapshot_id is not None:
            payload["snapshot_id"] = snapshot_id
        return self._json("POST", f"/api/revisions/{revision_id}/checkout/", payload)

    def get_active_checkouts(self):
        return self._json("GET", "/api/checkouts/active/")["checkouts"]

    def get_checkout_manifest(self, checkout_id):
        return self._json("GET", f"/api/checkouts/{checkout_id}/manifest/")

    def add_checkout_file(self, checkout_id, revision_id):
        return self._json(
            "POST",
            f"/api/checkouts/{checkout_id}/files/add/",
            {"revision_id": revision_id},
        )

    def remove_checkout_file(self, checkout_id, path):
        return self._json(
            "POST",
            f"/api/checkouts/{checkout_id}/files/remove/",
            {"path": path},
        )

    def checkin(self, checkout_id, fcstd_path, change_summary):
        return self._multipart(
            f"/api/checkouts/{checkout_id}/checkin/",
            {"change_summary": change_summary},
            "file",
            Path(fcstd_path),
            "application/octet-stream",
        )

    def checkin_files(self, checkout_id, changed_files, change_summary):
        metadata = []
        files = []
        for index, changed_file in enumerate(changed_files):
            field_name = f"file_{index}"
            local_path = Path(changed_file["local_path"])
            metadata.append(
                {
                    "field": field_name,
                    "path": changed_file["path"],
                    "revision_id": changed_file.get("revision_id"),
                    "base_sha256": changed_file.get("base_sha256"),
                    "sha256": changed_file.get("sha256"),
                    "is_root": bool(changed_file.get("is_root")),
                }
            )
            files.append((field_name, local_path, "application/octet-stream"))
        return self._multipart_files(
            f"/api/checkouts/{checkout_id}/checkin/",
            {
                "change_summary": change_summary,
                "files_metadata": json.dumps(metadata, sort_keys=True),
            },
            files,
        )

    def cancel_checkout(self, checkout_id):
        return self._json("POST", f"/api/checkouts/{checkout_id}/cancel/", {})

    def get_annotations(self, part_id):
        return self._json("GET", f"/api/parts/{part_id}/annotations/")["annotations"]

    def create_annotation(self, part_id, data):
        return self._json("POST", f"/api/parts/{part_id}/annotations/", data)["annotation"]

    def update_annotation(self, annotation_id, data):
        return self._json("POST", f"/api/annotations/{annotation_id}/", data)["annotation"]

    def delete_annotation(self, annotation_id):
        return self._json("DELETE", f"/api/annotations/{annotation_id}/")

    def _url(self, path, absolute=False):
        if absolute:
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self, content_type=None):
        headers = {"Authorization": f"Bearer {self.api_token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _json(self, method, path, data=None):
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
        response = self._open(method, path, body=body, content_type="application/json")
        if response.status == 204:
            return {}
        return json.loads(response.read().decode("utf-8"))

    def _open(self, method, path, body=None, content_type=None, absolute=False):
        req = request.Request(
            self._url(path, absolute=absolute),
            data=body,
            headers=self._headers(content_type=content_type),
            method=method,
        )
        try:
            return request.urlopen(req, timeout=self.timeout)
        except error.HTTPError as exc:
            self._raise_api_error(exc)

    def _raise_api_error(self, exc):
        raw = exc.read()
        payload = {}
        message = exc.reason or f"HTTP {exc.code}"
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
                message = payload.get("error") or message
            except (UnicodeDecodeError, json.JSONDecodeError):
                text = raw.decode("utf-8", errors="replace")
                if "<html" in text.lower() or "<!doctype html" in text.lower():
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = " ".join(text.split())
                if len(text) > 300:
                    text = f"{text[:300]}..."
                message = f"HTTP {exc.code}: {message}"
                if text:
                    message = f"{message} - {text}"
        error_class = {
            401: AuthenticationError,
            403: PermissionDeniedError,
            404: NotFoundError,
            409: ConflictError,
        }.get(exc.code, APIError)
        raise error_class(exc.code, message, payload)

    def _multipart(self, path, fields, file_field, file_path, content_type):
        return self._multipart_files(
            path,
            fields,
            [(file_field, file_path, content_type)],
        )

    def _multipart_files(self, path, fields, files):
        boundary = "----FreeCADPLMAddonBoundary"
        chunks = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        for file_field, file_path, content_type in files:
            file_path = Path(file_path)
            filename = file_path.name
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    (
                        f'Content-Disposition: form-data; name="{file_field}"; '
                        f'filename="{filename}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                    file_path.read_bytes(),
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        response = self._open(
            "POST",
            path,
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        return json.loads(response.read().decode("utf-8"))
