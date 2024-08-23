from enum import Enum
from typing import TypedDict, Unpack

from fastapi import WebSocket
from pydantic import ValidationError
from tortoise.expressions import Q

from discovery.core.celery import celery
from discovery.db.models import Registry, Run
from discovery.routes.tasks import TaskRequest as RunTaskParameters

from .manager import BaseMessage, ConnectionManager


class QueryParameters(TypedDict):
    id: str
    owner_id: str


class AvailableActions(str, Enum):
    QUERY: str = "QUERY"
    RUN_TASK: str = "RUN_TASK"


class Message(BaseMessage):
    action: AvailableActions


class QueryMessage(Message):
    action: AvailableActions = AvailableActions.QUERY
    data: QueryParameters


class RunTaskMessage(Message):
    action: AvailableActions = AvailableActions.RUN_TASK
    data: RunTaskParameters


class RunsWebSocket(ConnectionManager):
    def __init__(self) -> None:
        super().__init__()

    def parse(self, message: dict[str, any]) -> RunTaskMessage | QueryMessage:
        message: Message = Message.model_validate(obj=message)
        if message.action == AvailableActions.QUERY:
            return QueryMessage.model_validate(obj=message.model_dump())
        if message.action == AvailableActions.RUN_TASK:
            return RunTaskMessage.model_validate(obj=message.model_dump())
        raise ValidationError(
            ValueError(f"Invalid action: {message['action']}"),
        )

    async def process(self, sender: WebSocket) -> None:
        try:
            message_json = await sender.receive_json()
            message = self.parse(message_json)
            if message.action == AvailableActions.QUERY:
                await self.process_query(sender, message)
            elif message.action == AvailableActions.RUN_TASK:
                await self.process_run_task(sender, message)
            else:
                await self.respond(
                    to=sender,
                    message=f"Invalid action: {message.action}",
                    success=False,
                )
        except ValidationError as err:
            await self.respond(to=sender, message=err.errors(), success=False)
        except Exception as err:
            await self.respond(to=sender, message=str(err), success=False)

    async def process_query(self, sender: WebSocket, message: QueryMessage) -> None:
        data = message.data
        runs = await self.get_runs(**data)
        await self.respond(to=sender, data=runs, success=True)

    async def process_run_task(self, sender: WebSocket, message: RunTaskMessage) -> None:
        data = message.data
        task = await Registry.filter(id=data.id).first()
        if task:
            result = celery.send_task(
                name="task_runner",
                kwargs={
                    "schema": task.schema,
                    "owner_id": data.owner_id,
                    "parent_id": data.parent_id,
                    "parameters": data.parameters,
                },
            )
        else:
            return await self.respond(
                to=sender,
                message=f"Invalid task: {data.task}",
                success=False,
            )
        await self.respond(to=sender, data={"id": result.id}, success=True)

    async def get_runs(self, **params: Unpack[QueryParameters]) -> list[dict[str, any]]:
        filters = Q(Q(id=params["id"]), Q(owner_id=params["owner_id"]), join_type="AND")
        query = await Run.filter(filters).first()
        if query is None:
            return []
        children = await query.children.all() or []
        return [
            {
                "id": run.id,
                "name": run.name,
                "parameters": run.parameters,
                "status": run.status,
                "result": run.result,
                "files": run.files,
                "started_at": run.started_at,
                "failed_at": run.failed_at,
                "completed_at": run.completed_at,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
            for run in [query, *children]
            if run is not None
        ]
