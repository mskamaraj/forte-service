"""Data-access layer for the forte-completion DynamoDB table.

One table records whether a user has completed each exercise of a program.
Items are keyed by the partition key ``completion_pk`` = ``{user_id}#{program_id}``
and the sort key ``exercise_id``.  Keying the partition on the composite of user
and program means a single query returns a user's whole completion set for a
program (Requirements 12.2, 14), while the sort key allows a point ``get``/upsert
of one exercise's completion (Requirement 13.1).

The partition key is derived from the record's ``user_id`` and ``program_id`` and
is therefore not stored on the Pydantic ``ExerciseCompletionRecord``: it is built
on write and dropped on read.
"""

from typing import Optional

from boto3.dynamodb.conditions import Key

from app.db.dynamo import get_completion_table
from app.models.completion import ExerciseCompletionRecord


class CompletionRepository:

    def __init__(self):
        self._table = get_completion_table()

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get(
        self, user_id: str, program_id: str, exercise_id: str
    ) -> Optional[ExerciseCompletionRecord]:
        """Fetch a single exercise-completion record by its composite key.

        Returns ``None`` when no record exists.  The service treats a missing
        record as the incomplete default (Requirements 13.3, 14.8).
        """
        response = self._table.get_item(
            Key={
                "completion_pk": self._completion_pk(user_id, program_id),
                "exercise_id": exercise_id,
            }
        )
        item = response.get("Item")
        return self._from_item(item) if item else None

    def list_for_program(
        self, user_id: str, program_id: str
    ) -> list[ExerciseCompletionRecord]:
        """Return every completion record for a user's program in one query.

        A single query on ``completion_pk`` loads the user's whole completion
        set for the program, which a content-tree rollup joins in memory
        (Requirements 12.2, 14).
        """
        response = self._table.query(
            KeyConditionExpression=Key("completion_pk").eq(
                self._completion_pk(user_id, program_id)
            ),
        )
        return [self._from_item(item) for item in response.get("Items", [])]

    # ── Writes ────────────────────────────────────────────────────────────────

    def put(self, record: ExerciseCompletionRecord) -> ExerciseCompletionRecord:
        """Unconditionally upsert a completion record.

        No condition expression is used, so a toggle simply replaces the prior
        value for the exercise (Requirements 13.1, 13.2).
        """
        self._table.put_item(Item=self._to_item(record))
        return record

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _completion_pk(user_id: str, program_id: str) -> str:
        """Derive the partition key ``{user_id}#{program_id}``."""
        return f"{user_id}#{program_id}"

    @classmethod
    def _to_item(cls, record: ExerciseCompletionRecord) -> dict:
        """Serialise a record for DynamoDB.

        Adds the derived ``completion_pk`` partition key, which is not stored on
        the Pydantic record.
        """
        item = record.model_dump()
        item["completion_pk"] = cls._completion_pk(
            record.user_id, record.program_id
        )
        return item

    @staticmethod
    def _from_item(item: dict) -> ExerciseCompletionRecord:
        """Deserialise a DynamoDB item into a record.

        The ``completion_pk`` partition key is derived from the record's fields,
        so it is dropped here rather than passed to the model.
        """
        return ExerciseCompletionRecord(
            **{k: v for k, v in item.items() if k != "completion_pk"}
        )
