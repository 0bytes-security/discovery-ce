import contextlib  # noqa: I001
from datetime import datetime
from typing import Any, Dict, List, Tuple

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError


from discovery.core import config, pusher
from discovery.db import models as Models


class BaseEventHandler:
    """
    Class for handling events related to a single run.

    Args:
        run_id (str): The ID of the run.

    Attributes:
        run_id (str): The ID of the run.

    """

    def __init__(self, run_id: str) -> None:
        """
        Initialize a new instance of the Events class.

        Args:
            run_id (str): The ID of the run.

        Returns:
            None

        """
        self.run_id: str = run_id

    async def before_start(
        self,
        name: str,
        owner_id: str,
        parent_id: str | None,
        params: Dict[str, Any],
    ) -> None:
        """
        Called before the run starts.

        Args:
            name (str): The run name.
            owner_id (str): The owner id.
            parent_id (str | None): The parent id, if applicable.
            params (Dict[str, Any]): The parameters passed to the run.

        Returns:
            None
        """
        await Models.Run(
            id=self.run_id,
            name=name,
            owner_id=owner_id,
            parent_id=parent_id,
            parameters=params,
        ).save()

    async def on_start(
        self,
    ) -> Tuple[datetime, str, str | None, List[Models.RunStatus]]:
        """
        Called when the run starts.

        Returns:
            Tuple[str, datetime, str, str | None, List[Models.RunStatus]]:
                A tuple containing started_at datetime, owner id,
                parent id, and a list of status changes.
        """
        run: Models.Run = await self.run
        prev_status: Models.RunStatus = run.status
        run.status = Models.RunStatus.RUNNING
        run.started_at = datetime.now(tz=config.timezone)
        await run.save()
        return (
            run.started_at,
            run.owner_id,
            run.parent_id,
            [prev_status, Models.RunStatus.RUNNING],
        )

    async def on_complete(
        self,
        result: Dict[str, Any],
        files: List[Dict[str, Any]],
    ) -> Tuple[datetime, str, str | None, List[Models.RunStatus]]:
        """
        Called when the run completes successfully.

        Args:
            result (Dict[str, Any]): The result of the run.
            files (List[Dict[str, Any]]): The files generated by the run.

        Returns:
            Tuple[datetime, str, str | None, List[Models.RunStatus]]:
                A tuple containing the completed_at datetime, owner id,
                parent id, and a list of status changes.
        """
        run: Models.Run = await self.run
        prev_status: Models.RunStatus = run.status
        run.result = result
        run.files = files
        run.status = Models.RunStatus.SUCCESS
        run.completed_at = datetime.now(tz=config.timezone)
        await run.save()
        return (
            run.completed_at,
            run.owner_id,
            run.parent_id,
            [prev_status, Models.RunStatus.SUCCESS],
        )

    async def on_error(self, error: Exception) -> Tuple[datetime, str, str | None, str, List[Models.RunStatus]]:
        """
        Called when the run encounters an error.

        Args:
            error (Exception): The error that occurred during the run.

        Returns:
            Tuple[datetime, str, str | None, str, List[Models.RunStatus]]:
                A tuple containing the failed_at datetime, owner id,
                parent id, error message, and a list of status changes.
        """
        run: Models.Run = await self.run
        prev_status: Models.RunStatus = run.status
        run.status = Models.RunStatus.FAILED
        run.errors.append(
            {
                "reason": error.__class__.__name__,
                "message": jsonable_encoder(error.errors()) if isinstance(error, ValidationError) else str(error),
            }
        )
        run.failed_at = datetime.now(tz=config.timezone)
        await run.save()
        return (
            run.failed_at,
            run.owner_id,
            run.parent_id,
            error.__class__.__name__,
            [prev_status, Models.RunStatus.FAILED],
        )

    @property
    async def run(self) -> Models.Run:
        """Get the run model from the database.

        Args:
            self.run_id (str): The ID of the run.

        Returns:
            Models.Run: The run model.
        """
        run: Models.Run | None = await Models.Run.filter(id=self.run_id).first()
        if not run:
            raise ValueError(f"Run with ID {self.run_id} not found")
        return run


class EventHandlerWithPusher(BaseEventHandler):
    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)

    async def before_start(
        self,
        name: str,
        owner_id: str,
        parent_id: str | None,
        params: Dict[str, Any],
    ) -> None:
        await super().before_start(name, owner_id, parent_id, params)
        with contextlib.suppress(Exception):
            pusher.get_pusher_client().trigger(
                channels=pusher.Channels.RUNS,
                event_name=pusher.Events.RUN_CREATED,
                data={
                    "id": self.run_id,
                    "owner_id": owner_id,
                    "parent_id": parent_id,
                    "params": params,
                },
            )

    async def on_start(self) -> None:
        started_at, owner_id, parent_id, status = await super().on_start()
        with contextlib.suppress(Exception):
            pusher.get_pusher_client().trigger(
                channels=pusher.Channels.RUNS,
                event_name=pusher.Events.RUN_STATUS_CHANGED,
                data=jsonable_encoder(
                    {
                        "id": self.run_id,
                        "started_at": started_at,
                        "owner_id": owner_id,
                        "parent_id": parent_id,
                        "status": jsonable_encoder(status),
                    }
                ),
            )

    async def on_complete(self, result: Dict[str, Any], files: List[Dict[str, Any]]) -> None:
        completed_at, owner_id, parent_id, status = await super().on_complete(result, files)
        with contextlib.suppress(Exception):
            pusher.get_pusher_client().trigger(
                channels=pusher.Channels.RUNS,
                event_name=pusher.Events.RUN_STATUS_CHANGED,
                data=jsonable_encoder(
                    {
                        "id": self.run_id,
                        "completed_at": completed_at,
                        "owner_id": owner_id,
                        "parent_id": parent_id,
                        "status": status,
                    }
                ),
            )

    async def on_error(self, error: Exception) -> None:
        failed_at, owner_id, parent_id, error_msg, status = await super().on_error(error)
        with contextlib.suppress(Exception):
            pusher.get_pusher_client().trigger(
                channels=pusher.Channels.RUNS,
                event_name=pusher.Events.RUN_STATUS_CHANGED,
                data=jsonable_encoder(
                    {
                        "id": self.run_id,
                        "failed_at": failed_at,
                        "owner_id": owner_id,
                        "parent_id": parent_id,
                        "error": error_msg,
                        "status": status,
                    }
                ),
            )
