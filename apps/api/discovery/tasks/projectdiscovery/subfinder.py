from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Unpack

from celery import Task

from discovery.core import config
from discovery.core.celery import celery
from discovery.db.models import Run as Model
from discovery.db.models import RunStatus as Status
from discovery.runs.run import DefaultParameters, Run, RunResult
from discovery.runs.run import ParamsValidator as ParamsValidator


class Parameters(DefaultParameters):
    domain: str


@dataclass
class Result:
    domains: list[str]


BASE = Run[Parameters]


class Task(BASE):
    def __init__(self, task: Task) -> None:
        super().__init__(
            image="projectdiscovery/subfinder:latest",
            task=task,
        )

    async def run(self, **params: Unpack[Parameters]) -> RunResult:
        domain = params.get("domain")
        mounted = self.container_volume.mount()
        command = f"-d {domain}\r" f"-o {mounted.guest}/domains.txt"
        try:
            await self.container.run(
                image=self.image,
                command=command,
                volume=mounted,
                on_start=lambda: self.on_started(),
                on_finish=lambda: self.on_finished(),
            )
            return RunResult(self.task.request.id)

        except Exception as e:
            await self.on_error(error=str(e))
            raise
        finally:
            self.container_volume.cleanup()

    async def on_finished(self) -> None:
        """Called when the container run is finished."""
        run = await Model.filter(id=self.task.request.id).first()
        if run:
            prev_status = run.status
            domains = self.get_domains()
            run.result = asdict(domains)
            run.files = [
                asdict(file) for file in self.container_volume.upload_files_to_s3()
            ]
            run.status = Status.SUCCESS
            run.completed_at = datetime.now(tz=config.timezone)
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
            celery.send_task(
                name="discovery.tasks.projectdiscovery.httpx",
                kwargs={
                    "owner_id": run.owner_id,
                    "parent_id": run.id,
                    "domains": domains.domains,
                },
            )

    def get_domains(self) -> Result:
        domains = self.container_volume.read("domains.txt").splitlines()
        if isinstance(domains, list):
            return Result(
                domains=[domain for domain in domains],
            )

        return Result(domains=[])
