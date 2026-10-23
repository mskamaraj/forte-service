"""Data-access layer for the forte-enrollments DynamoDB table.

Each item records a single user's enrollment in a single program.  Items are
keyed by the partition key ``user_id`` and the sort key ``program_id``, so the
composite key makes an enrollment unique per (user_id, program_id) and a query
on ``user_id`` returns all of a user's enrollments (Requirement 11.1).
"""

from typing import Optional

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.db.dynamo import get_enrollments_table
from app.models.enrollment import EnrollmentRecord


class EnrollmentRepository:

    def __init__(self):
        self._table = get_enrollments_table()

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(self, user_id: str, program_id: str) -> Optional[EnrollmentRecord]:
        """Fetch a single enrollment by its composite key.

        Returns ``None`` when the user is not enrolled in the program.
        """
        response = self._table.get_item(
            Key={"user_id": user_id, "program_id": program_id}
        )
        item = response.get("Item")
        return EnrollmentRecord(**item) if item else None

    def list_by_user(self, user_id: str) -> list[EnrollmentRecord]:
        """Return every enrollment for a user in a single query on the PK."""
        response = self._table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
        )
        return [EnrollmentRecord(**item) for item in response.get("Items", [])]

    # ── Writes ────────────────────────────────────────────────────────────────

    def create(self, record: EnrollmentRecord) -> EnrollmentRecord:
        """
        Insert a new enrollment.  Uses a condition expression on the composite
        key to guard against a duplicate enrollment — including a losing racer
        under concurrency — so the service can map the conditional failure to a
        409 (Requirement 10.8).
        """
        try:
            self._table.put_item(
                Item=record.model_dump(),
                # Reject the write if an enrollment with this composite key
                # already exists.  ``attribute_not_exists`` on the partition-key
                # attribute is evaluated against the item at the full composite
                # key, so it fails only when (user_id, program_id) is taken.
                ConditionExpression="attribute_not_exists(user_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(
                    f"User {record.user_id} is already enrolled in program "
                    f"{record.program_id}"
                )
            raise
        return record
