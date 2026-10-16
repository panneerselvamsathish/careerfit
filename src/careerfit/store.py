"""Where usage records, the waitlist and donated job descriptions are kept.

Composition-root code, like cache.py: the API and the usage report use it; the pipeline never does.
This is the only module that imports boto3 (tests/test_architecture.py checks that).
"""

from typing import Any, Iterable, Protocol


class Store(Protocol):
    def put(self, record: dict[str, Any]) -> None: ...
    def delete(self, pk: str, sk: str) -> None: ...
    def query(self, pk: str) -> Iterable[dict[str, Any]]: ...
    def count(self, pk: str) -> int: ...


class MemoryStore:
    """For local runs and tests: nothing survives a restart."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}

    def put(self, record: dict[str, Any]) -> None:
        self.records[(record["pk"], record["sk"])] = dict(record)

    def delete(self, pk: str, sk: str) -> None:
        self.records.pop((pk, sk), None)

    def query(self, pk: str) -> list[dict[str, Any]]:
        return [r for (p, _), r in sorted(self.records.items()) if p == pk]

    def count(self, pk: str) -> int:
        return len(self.query(pk))


class DynamoStore:
    """One DynamoDB table, keyed by pk (partition) and sk (sort). The function's role may only put and
    delete items in it; queries come from the usage report, run with the owner's own credentials."""

    def __init__(self, table_name: str, session: Any = None) -> None:
        import boto3  # imported here, so local runs and tests without AWS never load it

        self.table = (session or boto3.session.Session()).resource("dynamodb").Table(table_name)

    def put(self, record: dict[str, Any]) -> None:
        self.table.put_item(Item=record)

    def delete(self, pk: str, sk: str) -> None:
        self.table.delete_item(Key={"pk": pk, "sk": sk})

    def query(self, pk: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items, start = [], None
        while True:
            extra = {"ExclusiveStartKey": start} if start else {}
            page = self.table.query(KeyConditionExpression=Key("pk").eq(pk), **extra)
            items.extend(_plain(i) for i in page["Items"])
            start = page.get("LastEvaluatedKey")
            if not start:
                return items

    def count(self, pk: str) -> int:
        from boto3.dynamodb.conditions import Key

        total, start = 0, None
        while True:
            extra = {"ExclusiveStartKey": start} if start else {}
            page = self.table.query(KeyConditionExpression=Key("pk").eq(pk), Select="COUNT", **extra)
            total += page["Count"]
            start = page.get("LastEvaluatedKey")
            if not start:
                return total


def _plain(value: Any) -> Any:
    """DynamoDB returns numbers as Decimal; every number careerfit stores is a whole count."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value
