import asyncio
from dataclasses import asdict
from typing import Any, Dict, NotRequired, TypedDict, Unpack
from uuid import uuid4

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from tortoise import Tortoise

from discovery.core import config
from discovery.db import init as init_database
from discovery.runs.run import TaskRunner


class TaskRunnerKwargs(TypedDict):
    schema: Dict[str, Any]
    owner_id: str
    parent_id: NotRequired[str]
    parameters: Dict[str, Any]


celery = Celery(
    "discovery",
    broker=config.celery_config.broker_url,
    backend=config.celery_config.result_backend,
    broker_connection_retry_on_startup=True,
)


@worker_process_init.connect
def worker_init(**kwargs) -> None:
    asyncio.run(init_database())


@worker_process_shutdown.connect
def worker_shutdown(**kwargs) -> None:
    asyncio.run(Tortoise.close_connections())


@celery.task(name="task_runner", bind=True)
def task_runner(celery_instance: Celery, **kwargs: Unpack[TaskRunnerKwargs]):
    runner = TaskRunner(
        task_schema=kwargs.get("schema"),
        request_id=celery_instance.request.id or str(uuid4()),
    )
    runner.ownership = {
        "owner_id": kwargs.get("owner_id"),
        "parent_id": kwargs.get("parent_id", None),
    }
    runner.parameters = kwargs.get("parameters")
    result = asyncio.run(runner.invoke())
    return asdict(result)


__all__ = [
    "celery",
]
