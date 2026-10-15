"""Data-access layer for the forte-users DynamoDB table."""

from typing import Optional
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.db.dynamo import get_users_table
from app.models.user import UserRecord


class UserRepository:

    def __init__(self):
        self._table = get_users_table()

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_by_id(self, user_id: str) -> Optional[UserRecord]:
        """Fetch a user by primary key."""
        response = self._table.get_item(Key={"user_id": user_id})
        item = response.get("Item")
        return UserRecord(**item) if item else None

    def get_by_email(self, email: str) -> Optional[UserRecord]:
        """Fetch a user by email using the email-index GSI."""
        response = self._table.query(
            IndexName="email-index",
            KeyConditionExpression=Key("email").eq(email),
            Limit=1,
        )
        items = response.get("Items", [])
        return UserRecord(**items[0]) if items else None

    def email_exists(self, email: str) -> bool:
        """Return True if the email is already registered."""
        response = self._table.query(
            IndexName="email-index",
            KeyConditionExpression=Key("email").eq(email),
            # Fetch only the PK — minimises read cost
            ProjectionExpression="user_id",
            Limit=1,
        )
        return len(response.get("Items", [])) > 0

    def list_all(
        self,
        limit: int = 50,
        start_key: Optional[dict] = None,
    ) -> tuple[list[UserRecord], Optional[dict]]:
        """
        Scan the table for a page of users.

        Returns a tuple of (records, last_evaluated_key). When
        last_evaluated_key is None, there are no more pages.
        """
        scan_kwargs: dict = {"Limit": limit}
        if start_key:
            scan_kwargs["ExclusiveStartKey"] = start_key

        response = self._table.scan(**scan_kwargs)
        records = [UserRecord(**item) for item in response.get("Items", [])]
        return records, response.get("LastEvaluatedKey")

    # ── Writes ────────────────────────────────────────────────────────────────

    def create(self, record: UserRecord) -> UserRecord:
        """
        Insert a new user.  Uses a condition expression to guard against
        a race condition where two requests register the same email
        simultaneously.
        """
        try:
            self._table.put_item(
                Item=record.model_dump(),
                # Reject the write if a record with this user_id already exists
                ConditionExpression="attribute_not_exists(user_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"User with id {record.user_id} already exists")
            raise
        return record
