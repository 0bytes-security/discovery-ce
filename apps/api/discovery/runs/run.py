import asyncio
import contextlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import (
    Generic,
    Literal,
    NotRequired,
    TypedDict,
    TypeVar,
    Unpack,
    get_args,
    get_origin,
)

from celery import Task
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError, field_validator

from discovery.containers.container import Container
from discovery.containers.volume import ContainerVolume
from discovery.core import config, pusher
from discovery.db.models import Run as Model
from discovery.db.models import RunStatus as Status
from discovery.utils import validate_domain


class DefaultParameters(TypedDict):
    owner_id: str
    parent_id: NotRequired[str]


@dataclass
class RunResult:
    id: str


T = TypeVar("T")


class GenericParamsValidator(BaseModel, Generic[T]):
    params: T

    class Config:
        arbitrary_types_allowed = True


class ParamsValidator(GenericParamsValidator[T], Generic[T]):
    @field_validator("params", check_fields=False)
    def domain_must_be_registered(cls, options: Unpack[T]) -> str:
        if "domain" in options and validate_domain(options["domain"]) is False:
            msg = "Invalid domain."
            raise ValueError(msg)

        return options


Parameters = TypeVar("Parameters", bound=DefaultParameters)


class TriggerEventKwargs(TypedDict):
    id: str
    image: str
    owner_id: str
    parent_id: NotRequired[str]
    params: NotRequired[dict]
    status: list[Status]


class Run(ABC, Generic[Parameters]):
    def __init__(
        self,
        image: str,
        task: Task,
        container: Container | None = None,
        container_volume: ContainerVolume | None = None,
    ) -> None:
        if not image:
            raise ValueError("No image provided")

        self._image = image
        self._task = task
        self._container = container or Container(docker_config=config.docker_config)
        self._container_volume = container_volume or ContainerVolume(
            base_path=config.docker_config.volumes_path
        )

    def _get_parameters(self):
        orig_bases = self.__orig_bases__
        for base in orig_bases:
            if get_origin(base) is Run:
                return get_args(base)[0]
        return None

    @abstractmethod
    def run(self, **params: Unpack[Parameters]) -> RunResult:
        """Run the task and return the result."""

    async def on_created(self, **params: Unpack[Parameters]) -> None:
        """Called when the container is created."""
        await Model(
            id=self.task.request.id,
            name=self.image,
            parameters=params,
            owner_id=params.get("owner_id"),
            parent=params.get("parent_id"),
        ).save()
        self.trigger_event(
            event="run.created",
            id=self.task.request.id,
            image=self.image,
            owner_id=params.get("owner_id"),
            parent_id=params.get("parent_id"),
            params=params,
            status=[Status.PENDING],
        )

    async def on_started(self) -> None:
        """Called when the container is started."""
        run = await Model.filter(id=self.task.request.id).first()
        if run:
            prev_status = run.status
            run.status = Status.RUNNING
            run.started_at = datetime.now(tz=config.timezone)
            await run.save()
            self.trigger_event(
                event="run.status.changed",
                id=self.task.request.id,
                owner_id=run.owner_id,
                parent_id=run.parent_id,
                image=self.image,
                status=[
                    prev_status.value,
                    run.status.value,
                ],
            )

    @abstractmethod
    async def on_finished(self) -> None:
        """Called when the container run is finished."""

    async def on_error(self, error: dict[str, str]) -> None:
        run = await Model.filter(id=self.task.request.id).first()
        if run:
            prev_status = run.status
            run.status = Status.FAILED
            run.errors.append(
                jsonable_encoder(
                    {
                        "message": error,
                        "timestamp": datetime.now(
                            tz=config.timezone,
                        ).isoformat(),
                    }
                )
            )
            run.failed_at = datetime.now(tz=config.timezone)
            await run.save()
            self.trigger_event(
                event="run.status.changed",
                id=self.task.request.id,
                owner_id=run.owner_id,
                parent_id=run.parent_id,
                image=self.image,
                status=[
                    prev_status.value,
                    run.status.value,
                ],
            )

    def validate_parameters(self, **params: Unpack[Parameters]) -> None:
        """Validate the parameters."""
        try:
            prams_cls = self._get_parameters()
            asyncio.run(self.on_created(**params))
            ParamsValidator[prams_cls].model_validate(
                obj={"params": params},
                strict=True,
            )
        except ValidationError as err:
            asyncio.run(self.on_error(error=err.errors()))
            raise err

    def trigger_event(
        self,
        event: Literal["run.created", "run.status.changed"],
        **kwargs: Unpack[TriggerEventKwargs],
    ) -> None:
        with contextlib.suppress(Exception):
            pusher.get_pusher_client().trigger(
                pusher.Channels.RUNS,
                event,
                data=kwargs,
            )

    @property
    def image(self) -> str:
        """Return the container image name."""
        return self._image

    @property
    def task(self) -> Task:
        """Return an instance of the Celery Task class."""
        return self._task

    @property
    def container_volume(self) -> ContainerVolume:
        """Return an instance of the ContainerVolume class."""
        return self._container_volume

    @property
    def container(self) -> Container:
        """Return an instance of the Container class."""
        return self._container
