import base64
import json
from dataclasses import asdict
from datetime import datetime
from typing import Unpack

from celery import Task
from pydantic import BaseModel, Field

from discovery.core import config
from discovery.db.models import Run as Model
from discovery.db.models import RunStatus as Status
from discovery.runs.run import DefaultParameters, Run, RunResult
from discovery.utils import validate_domain


class Item(BaseModel):
    ip_address: list[str] = Field(alias="a")
    body: str | None = Field(default="")
    content_length: int = Field(alias="content_length")
    content_type: str | None = Field(alias="content_type", default="")
    success: bool = Field(alias="failed")
    headers: dict[str, str] = Field(alias="header")
    host: str = Field(alias="host")
    method: str = Field(alias="method")
    path: str = Field(alias="path")
    port: str = Field(alias="port")
    raw_headers: str = Field(alias="raw_header")
    request: str = Field(alias="request")
    resolvers: list[str] = Field(alias="resolvers")
    scheme: str = Field(alias="scheme")
    status_code: int = Field(alias="status_code")
    technologies: list[str] = Field(alias="tech")
    response_time: str = Field(alias="time")
    timestamp: str = Field(alias="timestamp")
    title: str | None = Field(alias="title", default="")
    url: str = Field(alias="url")
    webserver: str = Field(alias="webserver")
    screenshot: str = Field(alias="screenshot_path_rel")


class Items(BaseModel):
    items: list[Item]


class Parameters(DefaultParameters):
    domains: list[str]


BASE = Run[Parameters]


class Task(BASE):
    def __init__(self, task: Task) -> None:
        super().__init__(
            image="projectdiscovery/httpx:latest",
            task=task,
        )

    async def run(self, **params: Unpack[Parameters]) -> RunResult:
        mounted = self.container_volume.mount()
        command: str = (
            " --json \r"
            "-no-fallback \r"
            "-screenshot \r"
            "-tech-detect\r"
            "-ip\r"
            "-cname\r"
            "-word-count\r"
            "-line-count\r"
            "-response-time\r"
            "-cdn\r"
            "-include-response\r"
            "-silent\r"
            "-stats\r"
            "-follow-host-redirects\r"
            "-max-redirects 2\r"
            f"-l {mounted.guest}/domains.txt\r"
            f"-o {mounted.guest}/results.json\r"
            f"-srd {mounted.guest}"
        )
        self.export_domains(params.get("domains"))
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
            run.result = self.parse_results().model_dump()
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

    def export_domains(self, domains: list[str]) -> None:
        path = "domains.txt"
        self.container_volume.write(
            path, "\n".join([domain for domain in domains if validate_domain(domain)])
        )

    def parse_results(self) -> Items:
        results_json = self.container_volume.read("results.json")
        items = [self.parse_item(item) for item in results_json.splitlines()]
        return Items(items=items)

    def parse_item(self, item: str) -> Item:
        parsed = json.loads(item)
        parsed["screenshot_path_rel"] = self.convert_screenshot_to_base64(
            parsed["screenshot_path_rel"],
        )

        return Item(**parsed)

    def convert_screenshot_to_base64(self, path: str) -> str:
        if self.container_volume.file_exists(f"screenshot/{path}"):
            screenshot = self.container_volume.read(
                path=f"screenshot/{path}",
                read_bytes=True,
            )
            return base64.b64encode(screenshot).decode("utf-8")

        return ""
