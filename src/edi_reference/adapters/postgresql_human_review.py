"""PostgreSQL append-only persistence for human review provenance."""

import json
from collections.abc import Callable
from typing import Any

from edi_reference.domain.human_review import HumanReview, ReviewAction, ReviewActionType


class ReviewVersionConflict(Exception):
    pass


class PostgreSqlHumanReviewRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def append(self, review: HumanReview, *, expected_version: int) -> None:
        if review.review_version != expected_version + 1:
            raise ReviewVersionConflict("REVIEW_VERSION_CONFLICT")

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT review_version
                       FROM processing.human_review
                       WHERE review_id=%s
                       ORDER BY review_version DESC
                       LIMIT 1
                       FOR UPDATE""",
                    (review.review_id,),
                )
                row = cursor.fetchone()
                current_version = -1 if row is None else int(row[0])
                if current_version != expected_version:
                    raise ReviewVersionConflict("REVIEW_VERSION_CONFLICT")

                cursor.execute(
                    """INSERT INTO processing.human_review
                       (review_id,review_version,result_id,result_version,actor_id,created_at)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        review.review_id,
                        review.review_version,
                        review.result_id,
                        review.result_version,
                        review.actor_id,
                        review.created_at,
                    ),
                )
                for ordinal, action in enumerate(review.actions):
                    cursor.execute(
                        """INSERT INTO processing.human_review_action
                           (review_id,review_version,action_ordinal,action,field_name,value,reason)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            review.review_id,
                            review.review_version,
                            ordinal,
                            action.action.value,
                            action.field,
                            json.dumps(action.value, separators=(",", ":"))
                            if action.value is not None
                            else None,
                            action.reason,
                        ),
                    )

    def get(self, review_id: str, review_version: int) -> HumanReview | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT result_id,result_version,actor_id,created_at
                       FROM processing.human_review
                       WHERE review_id=%s AND review_version=%s""",
                    (review_id, review_version),
                )
                root = cursor.fetchone()
                if root is None:
                    return None
                cursor.execute(
                    """SELECT action,field_name,value,reason
                       FROM processing.human_review_action
                       WHERE review_id=%s AND review_version=%s
                       ORDER BY action_ordinal""",
                    (review_id, review_version),
                )
                actions = tuple(
                    ReviewAction(
                        action=ReviewActionType(row[0]),
                        field=row[1],
                        value=row[2],
                        reason=row[3],
                    )
                    for row in cursor.fetchall()
                )
        return HumanReview(
            review_id=review_id,
            review_version=review_version,
            result_id=root[0],
            result_version=root[1],
            actor_id=root[2],
            actions=actions,
            created_at=root[3],
        )
