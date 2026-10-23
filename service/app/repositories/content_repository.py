"""Data-access layer for the forte-content DynamoDB table.

One table holds every content node (modules, chapters, exercises) for all
programs.  Items are keyed by the partition key ``program_id`` and the sort key
``node_sk`` = ``{node_type}#{node_id}``, so a single query on ``program_id``
returns a program's entire hierarchy (Requirement 12.1).
"""

from typing import Optional

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.db.dynamo import get_content_table
from app.models.content import ContentNodeRecord


class ContentRepository:

    def __init__(self):
        self._table = get_content_table()

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_node(self, program_id: str, node_sk: str) -> Optional[ContentNodeRecord]:
        """Fetch a single content node by its composite key.

        ``node_sk`` is ``{node_type}#{node_id}``.  Used for ownership and
        ancestry checks in the service layer.
        """
        response = self._table.get_item(
            Key={"program_id": program_id, "node_sk": node_sk}
        )
        item = response.get("Item")
        return self._from_item(item) if item else None

    def list_for_program(self, program_id: str) -> list[ContentNodeRecord]:
        """Return every content node for a program in a single query.

        Returns all modules, chapters, and exercises; the service builds and
        orders the tree in memory (Requirement 12.1).
        """
        response = self._table.query(
            KeyConditionExpression=Key("program_id").eq(program_id),
        )
        return [self._from_item(item) for item in response.get("Items", [])]

    # ── Writes ────────────────────────────────────────────────────────────────

    def create(self, record: ContentNodeRecord) -> ContentNodeRecord:
        """Insert a content node (module, chapter, or exercise)."""
        self._table.put_item(Item=self._to_item(record))
        return record

    def update_node(self, record: ContentNodeRecord) -> ContentNodeRecord:
        """
        Overwrite an existing content node.  The condition expression ensures
        the node exists, so an update against a missing node fails rather than
        silently creating one.
        """
        try:
            self._table.put_item(
                Item=self._to_item(record),
                # Reject the write unless a node with this sort key exists
                ConditionExpression="attribute_exists(node_sk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(
                    f"Content node {self._node_sk(record)} does not exist"
                )
            raise
        return record

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _node_sk(record: ContentNodeRecord) -> str:
        """Derive the sort key ``{node_type}#{node_id}`` for a record."""
        return f"{record.node_type.value}#{record.node_id}"

    @classmethod
    def _to_item(cls, record: ContentNodeRecord) -> dict:
        """Serialise a record for DynamoDB.

        Renders the ``NodeType`` enum as its string value and adds the derived
        ``node_sk`` sort key, which is not stored on the Pydantic record.
        """
        item = record.model_dump()
        item["node_type"] = record.node_type.value
        item["node_sk"] = cls._node_sk(record)
        return item

    @staticmethod
    def _from_item(item: dict) -> ContentNodeRecord:
        """Deserialise a DynamoDB item into a record.

        The ``node_sk`` sort key is derived from the record's fields, so it is
        dropped here rather than passed to the model.
        """
        return ContentNodeRecord(
            **{k: v for k, v in item.items() if k != "node_sk"}
        )
