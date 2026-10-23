"""Data-access layer for the forte-programs DynamoDB table."""

from typing import Optional

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.db.dynamo import get_programs_table
from app.models.program import ProgramRecord, ProgramState


class ProgramRepository:

    def __init__(self):
        self._table = get_programs_table()

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_by_id(self, program_id: str) -> Optional[ProgramRecord]:
        """Fetch a program by primary key."""
        response = self._table.get_item(Key={"program_id": program_id})
        item = response.get("Item")
        return ProgramRecord(**item) if item else None

    def list_by_coach(self, coach_id: str) -> list[ProgramRecord]:
        """List the programs owned by a coach using the owner-index GSI."""
        response = self._table.query(
            IndexName="owner-index",
            KeyConditionExpression=Key("owner_coach_id").eq(coach_id),
        )
        return [ProgramRecord(**item) for item in response.get("Items", [])]

    def list_active(self) -> list[ProgramRecord]:
        """List all active programs using the state-index GSI (no scan)."""
        response = self._table.query(
            IndexName="state-index",
            KeyConditionExpression=Key("program_state").eq(ProgramState.active.value),
        )
        return [ProgramRecord(**item) for item in response.get("Items", [])]

    # ── Writes ────────────────────────────────────────────────────────────────

    def create(self, record: ProgramRecord) -> ProgramRecord:
        """
        Insert a new program.  Uses a condition expression to guard against
        a race condition where two requests create the same program id
        simultaneously.
        """
        try:
            self._table.put_item(
                Item=self._to_item(record),
                # Reject the write if a record with this program_id already exists
                ConditionExpression="attribute_not_exists(program_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"Program with id {record.program_id} already exists")
            raise
        return record

    def update(self, record: ProgramRecord) -> ProgramRecord:
        """
        Overwrite an existing program.  The condition expression ensures the
        program exists, so an update against a missing program fails rather
        than silently creating one.
        """
        try:
            self._table.put_item(
                Item=self._to_item(record),
                # Reject the write unless a record with this program_id exists
                ConditionExpression="attribute_exists(program_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"Program with id {record.program_id} does not exist")
            raise
        return record

    def transition_state(
        self,
        program_id: str,
        expected_state: ProgramState,
        new_state: ProgramState,
        updated_at: str,
    ) -> ProgramRecord:
        """
        Conditionally move a program from ``expected_state`` to ``new_state``.

        The condition expression guards against a concurrent transition: if the
        stored ``program_state`` no longer matches ``expected_state`` the update
        fails rather than clobbering the newer state.
        """
        try:
            response = self._table.update_item(
                Key={"program_id": program_id},
                UpdateExpression="SET program_state = :new, updated_at = :updated",
                ConditionExpression="program_state = :expected",
                ExpressionAttributeValues={
                    ":new": new_state.value,
                    ":updated": updated_at,
                    ":expected": expected_state.value,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(
                    f"Program {program_id} is not in expected state {expected_state.value}"
                )
            raise
        return ProgramRecord(**response["Attributes"])

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_item(record: ProgramRecord) -> dict:
        """Serialise a record for DynamoDB.

        ``mode="json"`` renders the ``ProgramState`` enum as its string value;
        ``price`` is kept as a ``Decimal`` since DynamoDB stores numbers as
        Decimals and float coercion would introduce drift.
        """
        item = record.model_dump()
        item["program_state"] = record.program_state.value
        return item
