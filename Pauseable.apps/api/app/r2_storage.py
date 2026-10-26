from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class R2ConfigurationError(RuntimeError):
    pass


def _validate_object_key(key: str) -> None:
    parts = key.split("/")

    if (
        not key
        or key.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Invalid R2 object key: {key!r}")


def _is_precondition_failed(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    status_code = error.response.get("ResponseMetadata", {}).get(
        "HTTPStatusCode"
    )
    return code in {
        "409",
        "412",
        "ConditionalRequestConflict",
        "PreconditionFailed",
    } or status_code in {409, 412}


def _encode_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


class R2Storage:
    def __init__(self, client: Any, bucket_name: str) -> None:
        self.client = client
        self.bucket_name = bucket_name

    @classmethod
    def from_environment(cls) -> "R2Storage":
        required_names = (
            "R2_ENDPOINT_URL",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_NAME",
        )
        values = {
            name: os.getenv(name, "").strip()
            for name in required_names
        }
        missing = [
            name
            for name, value in values.items()
            if not value
        ]

        if missing:
            raise R2ConfigurationError(
                "Missing R2 environment variables: "
                + ", ".join(missing)
            )

        client = boto3.client(
            "s3",
            endpoint_url=values["R2_ENDPOINT_URL"],
            aws_access_key_id=values["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
            region_name=os.getenv("R2_REGION", "auto"),
            config=Config(signature_version="s3v4"),
        )

        return cls(
            client=client,
            bucket_name=values["R2_BUCKET_NAME"],
        )

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        _validate_object_key(key)
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def get_bytes(self, key: str) -> bytes | None:
        _validate_object_key(key)

        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=key,
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

        return response["Body"].read()

    def object_exists(self, key: str) -> bool:
        _validate_object_key(key)

        try:
            self.client.head_object(
                Bucket=self.bucket_name,
                Key=key,
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

        return True

    def delete_object(self, key: str) -> None:
        _validate_object_key(key)
        self.client.delete_object(
            Bucket=self.bucket_name,
            Key=key,
        )

    def put_json(
        self,
        key: str,
        payload: dict[str, Any],
    ) -> None:
        self.put_bytes(
            key,
            _encode_json(payload),
            content_type="application/json; charset=utf-8",
        )

    def put_json_if_absent(
        self,
        key: str,
        payload: dict[str, Any],
    ) -> str | None:
        pass
        _validate_object_key(key)

        try:
            response = self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=_encode_json(payload),
                ContentType="application/json; charset=utf-8",
                IfNoneMatch="*",
            )
        except ClientError as error:
            if _is_precondition_failed(error):
                return None
            raise

        return str(response.get("ETag", "")) or None

    def put_json_if_match(
        self,
        key: str,
        payload: dict[str, Any],
        etag: str,
    ) -> str | None:
        pass
        _validate_object_key(key)
        if not etag:
            raise ValueError("ETag is required for a conditional JSON update")

        try:
            response = self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=_encode_json(payload),
                ContentType="application/json; charset=utf-8",
                IfMatch=etag,
            )
        except ClientError as error:
            if _is_precondition_failed(error):
                return None
            raise

        return str(response.get("ETag", "")) or None

    def get_json(self, key: str) -> dict[str, Any] | None:
        encoded = self.get_bytes(key)

        if encoded is None:
            return None

        payload = json.loads(encoded.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"R2 JSON object must be a dictionary: {key}")

        return payload

    def get_json_with_etag(
        self,
        key: str,
    ) -> tuple[dict[str, Any], str] | None:
        _validate_object_key(key)

        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=key,
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

        payload = json.loads(response["Body"].read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"R2 JSON object must be a dictionary: {key}")

        etag = str(response.get("ETag", ""))
        if not etag:
            raise ValueError(f"R2 object response is missing an ETag: {key}")

        return payload, etag

    def head_object(self, key: str) -> dict[str, Any] | None:
        _validate_object_key(key)

        try:
            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=key,
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

        return {
            "size_bytes": int(response["ContentLength"]),
            "etag": str(response.get("ETag", "")),
            "content_type": response.get("ContentType"),
            "metadata": dict(response.get("Metadata", {})),
        }

    def list_keys(self, prefix: str) -> list[str]:
        _validate_object_key(prefix.rstrip("/"))

        keys: list[str] = []
        continuation_token: str | None = None

        while True:
            arguments: dict[str, Any] = {
                "Bucket": self.bucket_name,
                "Prefix": prefix,
            }
            if continuation_token is not None:
                arguments["ContinuationToken"] = continuation_token

            response = self.client.list_objects_v2(**arguments)
            keys.extend(
                item["Key"]
                for item in response.get("Contents", [])
            )

            if not response.get("IsTruncated", False):
                break

            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                break

        return keys

    def create_upload_url(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int = 900,
        metadata: dict[str, str] | None = None,
        content_md5: str | None = None,
        content_length: int | None = None,
    ) -> str:
        _validate_object_key(key)
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": key,
            "ContentType": content_type,
        }
        if metadata:
            params["Metadata"] = metadata
        if content_md5:
            params["ContentMD5"] = content_md5
        if content_length is not None:
            if content_length <= 0:
                raise ValueError("Content length must be positive")
            params["ContentLength"] = content_length

        return str(
            self.client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires_seconds,
            )
        )

    def create_download_url(
        self,
        key: str,
        *,
        expires_seconds: int = 900,
    ) -> str:
        _validate_object_key(key)

        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                },
                ExpiresIn=expires_seconds,
            )
        )
