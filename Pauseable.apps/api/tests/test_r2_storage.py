from __future__ import annotations

import io
import json
import unittest

from botocore.exceptions import ClientError

from app.r2_storage import R2Storage


class FakeR2Client:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.fail_precondition = False

    def put_object(self, **arguments):
        self.put_calls.append(arguments)
        if self.fail_precondition:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        return {"ETag": '"new-etag"'}

    def get_object(self, **arguments):
        return {
            "Body": io.BytesIO(json.dumps({"status": "queued"}).encode()),
            "ETag": '"current-etag"',
        }


class R2StorageConditionalWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeR2Client()
        self.storage = R2Storage(self.client, "test-bucket")

    def test_create_uses_if_none_match(self) -> None:
        etag = self.storage.put_json_if_absent(
            "patients/test/claim.json",
            {"claim_id": "claim-one"},
        )

        self.assertEqual(etag, '"new-etag"')
        self.assertEqual(self.client.put_calls[0]["IfNoneMatch"], "*")
        self.assertNotIn("IfMatch", self.client.put_calls[0])

    def test_compare_and_swap_uses_current_etag(self) -> None:
        etag = self.storage.put_json_if_match(
            "patients/test/claim.json",
            {"claim_id": "claim-two"},
            '"current-etag"',
        )

        self.assertEqual(etag, '"new-etag"')
        self.assertEqual(
            self.client.put_calls[0]["IfMatch"],
            '"current-etag"',
        )

    def test_precondition_failure_returns_none(self) -> None:
        self.client.fail_precondition = True

        self.assertIsNone(
            self.storage.put_json_if_absent(
                "patients/test/claim.json",
                {"claim_id": "claim-one"},
            )
        )

    def test_json_read_preserves_etag(self) -> None:
        result = self.storage.get_json_with_etag(
            "patients/test/manifest.json"
        )

        self.assertEqual(
            result,
            ({"status": "queued"}, '"current-etag"'),
        )


if __name__ == "__main__":
    unittest.main()
