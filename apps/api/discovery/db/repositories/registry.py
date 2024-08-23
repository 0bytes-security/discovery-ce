from typing import Literal, TypedDict, Unpack

from fastapi_pagination.ext.tortoise import paginate

from ..models import Registry, SchemaType
from ..repository import Repository as BaseRepository


class FilterableColumns(TypedDict):
    type: SchemaType


class Repository(
    BaseRepository[
        Registry,
        Literal[
            "id",
            "parameters",
            "status",
            "result",
            "started_at",
            "failed_at",
            "completed_at",
            "owner_id",
            "created_at",
            "updated_at",
            "parent_id",
        ],
        FilterableColumns,
    ],
):
    def __init__(self) -> None:
        super().__init__(Registry)

    async def filter_by(
        self,
        **filters: Unpack[FilterableColumns],
    ) -> list[Registry]:
        expressions = self.generate_expressions(join_type="AND", **filters)

        return await paginate(self.model.filter(expressions).all())

    async def all_tasks(self) -> list[Registry]:
        return await self.model.filter(type=SchemaType.TASK).all()

    async def all_workflows(self) -> list[Registry]:
        return await self.model.filter(type=SchemaType.WORKFLOW).all()
