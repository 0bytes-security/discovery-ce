import csv
import json
import os
from dataclasses import dataclass
from io import StringIO
from string import Template
from typing import (
    Any,
    Dict,
    List,
    Literal,
    TypedDict,
    Union,
)
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from discovery.containers.container import Container
from discovery.containers.volume import ContainerVolume
from discovery.core import config
from discovery.schema.tasks import Task

from .events_handler import EventHandlerWithPusher


@dataclass
class RunResult:
    id: str


class OutputFiles(TypedDict):
    file_type: Literal["txt", "json", "jsonl", "csv"]
    path: str


class TaskRunner:
    """
    Handles the execution of a task within a containerized environment.

    Attributes:
        _task_schema Dict[str, Any]: The task schema associated with this task execution.
        _request_id (str): The Celery task ID associated with this task execution.
        _container (Container): The container instance used for running the task.
        _volume_manager (ContainerVolume): Manages the container volumes for the task.
        _parameters (Dict[str, Any]): Stores additional parameters required for task execution.
        _ownership_ids (Dict[Literal["owner_id", "parent_id"], str]): Stores ownership-related identifiers.
        _events_handler (EventHandlerWithPusher): Handles task execution events.

    Args:
        task Task: The task model.
        request_id (str): The Celery task ID.
        container (Container, optional): A container instance. Defaults to None.
        volume_manager (ContainerVolume, optional): Manages the container volumes. Defaults to None.
    """

    def __init__(
        self,
        task_schema: Dict[str, Any],
        request_id: str,
        container: Container | None = None,
        volume_manager: ContainerVolume | None = None,
    ) -> None:
        self._task = self.parse_task_schema(task_schema)
        self._request_id = request_id
        self._container = container or Container(docker_config=config.docker_config)
        self._volume_manager = volume_manager or ContainerVolume(base_path=config.docker_config.volumes_path)
        self._parameters: Dict[str, Any] = {}
        self._ownership_ids: Dict[Literal["owner_id", "parent_id"], str] = {}
        self.events_handler = EventHandlerWithPusher(run_id=self.request_id)
        self._files: Dict[str, OutputFiles] = {}

    async def invoke(self) -> RunResult:
        """
        Runs the task and returns the result.

        Returns:
            RunResult: The result of the task execution.
        """
        try:
            await self.events_handler.before_start(
                name=self.task.name or self.task.id,
                owner_id=self.ownership.get("owner_id"),
                parent_id=self.ownership.get("parent_id"),
                params=self.parameters,
            )

            command = self.prepare(self.parameters)
            await self.container.run(
                image=self.task.image,
                command=command,
                volume=self.volume_manager.mount(),
                on_start=lambda: self.events_handler.on_start(),
                on_finish=lambda: self.completed(),
            )

            return RunResult(id=self.request_id)
        except Exception as err:
            await self.events_handler.on_error(error=err)
            raise
        finally:
            # Cleanup
            if os.getenv("ENV_TYPE", "DEV") != "DEV":
                self.volume_manager.cleanup()

    def prepare(self, parameters: Dict[str, Any]) -> str:
        """
        Prepares the task runner.

        1. Validates the parameters against the task schema.
        2. Mounts the volumes.
        3. Prepares the command with the validated parameter values.

        Args:
            parameters (Dict[str, Any]): The user-provided parameters.

        Returns:
            str: The prepared command.
        """
        self.task.validate_parameters(parameters)

        mounted = self.volume_manager.mount()

        command = self.prepare_command(
            values=parameters,
            guest_volume_path=mounted.guest,
        )

        return command

    def prepare_command(
        self,
        values: Dict[str, Any],
        guest_volume_path: str,
    ) -> str:
        """
        Replaces placeholders in the command with values from the parameters.

        Args:
            values (Dict[str, Any]): The values to use for the placeholder replacement.
            guest_volume_path (str): The path to the volume inside the container.

        Returns:
            str: The command with placeholders replaced.
        """
        placeholders: Dict[str, str] = {"RUN_DIR": guest_volume_path}
        for key, placeholder in self.task.command_placeholders.items():
            if placeholder.get("type") == "INPUT" and placeholder.get("is_file"):
                file_path = self.write_file(
                    value=values[key],
                    file_type=placeholder["file_type"],
                )
                placeholders[key] = f"{guest_volume_path}/{file_path}"
            elif placeholder.get("type") == "OUTPUT" and placeholder.get("is_file"):
                placeholders[key] = f"{guest_volume_path}/{str(uuid4())}.{placeholder['file_type']}"
                self._files[key] = OutputFiles(
                    path=placeholders[key],
                    file_type=placeholder["file_type"],
                )
            else:
                placeholders[key] = str(values[key])
        return Template(self.task.command).safe_substitute(placeholders)

    def outputs(
        self,
    ) -> Dict[str, Union[List[str], str, Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Returns the contents of the output files as a dictionary.

        The keys are the output parameter names and the values are the contents of the files.
        """
        return {key: self.read_file(file_path=file["path"], file_type=file["file_type"]) for key, file in self._files.items()}

    async def completed(
        self,
    ) -> None:
        """
        Called when the task is completed.

        Args:
            None

        Returns:
            None
        """
        outputs = self.outputs()
        files = self.upload_files()
        await self.events_handler.on_complete(
            result=outputs,
            files=files,
        )

    def upload_files(self) -> List[Dict[str, Union[str, str]]]:
        """
        Uploads all files in the volume manager to S3 and returns a list of dictionaries
        containing the path and content type of each uploaded file.

        Returns:
            List[Dict[str, Union[str, str]]]: A list of dictionaries containing the path and content type
            of each uploaded file.
        """
        try:
            uploaded_files = self.volume_manager.upload_files_to_s3()
            return jsonable_encoder(uploaded_files)
        except Exception:
            return []

    def write_file(
        self,
        value: Union[List[str], str, Dict[str, Any], List[Dict[str, Any]]],
        file_type: Literal["txt", "json", "jsonl", "csv"],
    ) -> str:
        """
        Writes a given value to a file in the volume manager.

        Args:
            value (Union[List[str], str, Dict[str, Any], List[Dict[str, Any]]]):
                The value to be written to the file.
            file_type (Literal["txt", "json", "jsonl", "csv"]):
                The type of the file.

        Returns:
            str: The path of the created file.

        Raises:
            ValueError: If the file type is not supported.
            TypeError: If the value is not of the correct type.
        """
        file_path = f"{uuid4()}.{file_type}"
        match file_type:
            case "txt":
                if isinstance(value, list):
                    self.volume_manager.write(path=file_path, content="\n".join(value))
                    return file_path

                if isinstance(value, str):
                    self.volume_manager.write(path=file_path, content=value)
                    return file_path
                raise TypeError(f"Unsupported value type for txt file: {type(value)}")
            case "json":
                if isinstance(value, dict):
                    self.volume_manager.write(path=file_path, content=json.dumps(value))
                    return file_path

                raise TypeError(f"Unsupported value type for json file: {type(value)}")

            case "jsonl":
                if isinstance(value, list):
                    content = ""
                    for v in value:
                        content += json.dumps(v) + "\n"
                    self.volume_manager.write(path=file_path, content=content)
                    return file_path

                raise TypeError(f"Unsupported value type for jsonl file: {type(value)}")

            case "csv":
                if isinstance(value, dict):
                    content = StringIO()
                    fieldnames = list(value.keys())
                    to_csv = csv.DictWriter(content, fieldnames=fieldnames)
                    to_csv.writeheader()
                    to_csv.writerow(value)
                    self.volume_manager.write(path=file_path, content=content)
                    return file_path
                if isinstance(value, list):
                    content = StringIO()
                    if len(value) > 0:
                        fieldnames = list(value[0].keys())
                        to_csv = csv.DictWriter(content, fieldnames=fieldnames)
                        to_csv.writeheader()
                        to_csv.writerows(value)
                        self.volume_manager.write(path=file_path, content=content)
                        return file_path

                raise TypeError(f"Unsupported value type for csv file: {type(value)}")
            case _:
                raise ValueError(f"Unsupported file type: {file_type}")

    def read_file(
        self,
        file_path: str,
        file_type: Literal["txt", "json", "jsonl", "csv"],
    ) -> Union[List[str], Dict[str, Any], List[Dict[str, Any]], csv.DictReader]:
        """
        Reads a file from the volume manager and returns its contents based on the file type.

        Args:
            file_path (str): The path of the file to read.
            file_type (Literal["txt", "json", "jsonl", "csv"]): The type of the file.

        Returns:
            Union[List[str], Dict[str, Any], List[Dict[str, Any]], csv.DictReader]:
                The contents of the file, parsed based on the file type.

        Raises:
            ValueError: If the file type is not supported.
        """
        file_contents = self.volume_manager.read(path=file_path)
        match file_type:
            case "txt":
                return file_contents.splitlines()
            case "json":
                return json.loads(file_contents)
            case "jsonl":
                return [json.loads(line) for line in file_contents.splitlines() if line]
            case "csv":
                return csv.DictReader(StringIO(file_contents))
            case _:
                raise ValueError(f"Unsupported file type: {file_type}")

    def parse_task_schema(self, task_schema: Dict[str, Any]) -> Task:
        """
        Validates and parses a task schema based on the Task Pydantic model.

        Args:
            task_schema (Dict[str, Any]): The task schema to be validated and parsed.

        Returns:
            Task: The parsed task schema.

        Raises:
            ValidationError: If the task schema fails validation.
        """
        return Task.model_validate(task_schema)

    @property
    def task(self) -> Task:
        return self._task

    @property
    def container(self) -> Container:
        return self._container

    @property
    def volume_manager(self) -> ContainerVolume:
        return self._volume_manager

    @property
    def request_id(self) -> str:
        return self._request_id

    @request_id.setter
    def request_id(self, value: str) -> None:
        self._request_id = value

    @property
    def ownership(self) -> Dict[Literal["owner_id", "parent_id"], str]:
        return self._ownership_ids

    @ownership.setter
    def ownership(self, value: Dict[Literal["owner_id", "parent_id"], str]) -> None:
        self._ownership_ids = value

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters

    @parameters.setter
    def parameters(self, value: Dict[str, Any]) -> None:
        self._parameters = value
