import json
from typing import Any, Dict, Generator, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from fastapi_pagination import Page
from pydantic import BaseModel, Field, ValidationError
from tortoise.contrib.pydantic import pydantic_model_creator
from tortoise.exceptions import IntegrityError
from tortoise.exceptions import ValidationError as TortoiseValidationError

from discovery.core.celery import celery
from discovery.db.models import Registry, SchemaType
from discovery.db.repositories.registry import Repository
from discovery.runs.run import RunResult
from discovery.schema.tasks import Task
from discovery.utils import custom_generate_unique_id

router = APIRouter(prefix="/tasks", generate_unique_id_function=custom_generate_unique_id)
Model = pydantic_model_creator(Registry)


class TaskRequest(BaseModel):
    id: str = Field(..., description="The ID of the task in the registry.")
    parameters: dict[str, Any] = Field(..., description="The input parameters required for the task execution.")
    owner_id: str = Field(..., description="The ID of the owner who is executing the task.")
    parent_id: Optional[str] = Field(None, description="The ID of the parent task. If provided, this task will be considered a subtask of the parent task.")

    class Config:
        arbitrary_types_allowed = True


class InvalidYamlException(Exception):
    def __init__(self):
        super().__init__("Invalid YAML string.")

    pass


def safe_yaml_load(yaml_string: str) -> Optional[Dict[str, Any]]:
    from yaml import FullLoader, load

    try:
        data = load(yaml_string, Loader=FullLoader)
        if not isinstance(data, dict):
            raise TypeError("Invalid YAML string.")
        return data
    except Exception:
        raise InvalidYamlException from None


def get_repository() -> Generator[Repository, any, any]:
    """
    Dependency to provide a database repository instance.

    Yields:
        Repository: An instance of the repository for database operations.
    """
    repo = Repository()
    try:
        yield repo
    finally:
        del repo


@router.get(
    "",
    response_model=Page[Model],
    description="Retrieve all registered tasks with pagination. Results are paginated based on the creation date.",
    summary="Get All Registered Tasks",
    tags=["Tasks"],
    responses={
        200: {"description": "Successfully retrieved the paginated list of tasks."},
        500: {"description": "Internal server error."},
    },
)
async def all(
    repository: Repository = Depends(get_repository),  # noqa: B008
) -> Page[Registry]:
    """
    Retrieve all registered tasks with pagination.

    Args:
        repository (Repository): Dependency that provides a repository instance.

    Returns:
        Page[Registry]: Paginated list of tasks.

    Raises:
        HTTPException: If an internal server error occurs.
    """
    try:
        return await repository.filter_by(type=SchemaType.TASK)
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server Error") from None


@router.get(
    "/{task_id}",
    response_model=Model,
    tags=["Tasks"],
    description="Get a single task by its ID. If the ID is not found, a 404 response is returned.",
    summary="Get Task by ID",
    responses={
        200: {"description": "Successfully retrieved the task."},
        400: {"description": "Invalid task ID. Please provide a valid task ID."},
        404: {"description": "Task not found. Please provide a valid task ID."},
        500: {"description": "Server error."},
    },
)
async def get_by_id(
    task_id: str,
    repository: Repository = Depends(get_repository),  # noqa: B008
) -> Registry:
    """
    Retrieve a task by its ID.

    Args:
        task_id (str): The ID of the task to retrieve.
        repository (Repository): Dependency that provides a repository instance.

    Returns:
        Registry: The task with the specified ID.

    Raises:
        HTTPException: If the task is not found, the ID is invalid, or an internal server error occurs.
    """
    try:
        task = await repository.get_by_id(task_id)
        if task is None:
            raise repository.ItemNotFoundError
        return task
    except repository.ItemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found. Please provide a valid task ID.",
        ) from None
    except TortoiseValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid task ID. Please provide a valid task ID.",
        ) from None
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server Error") from None


@router.post(
    "",
    description="Upload and register a task schema in the registry. The task schema can be provided in either JSON or YAML format.",
    summary="Register a New Task",
    tags=["Tasks"],
    responses={
        201: {
            "description": "The task was successfully added to the registry.",
            "content": {"application/json": {"example": {"message": "Task registered successfully", "id": "task_12345"}}},
        },
        400: {
            "description": "Bad request due to invalid file type, invalid schema, or task already exists.",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_file_type": {
                            "summary": "Invalid File Type",
                            "value": {"detail": "Invalid file type, only JSON and YAML files are allowed."},
                        },
                        "invalid_json": {
                            "summary": "Invalid JSON File",
                            "value": {"detail": "Invalid JSON file. Please provide a valid JSON file."},
                        },
                        "invalid_yaml": {
                            "summary": "Invalid YAML File",
                            "value": {"detail": "Invalid YAML file. Please provide a valid YAML file."},
                        },
                        "validation_error": {
                            "summary": "Schema Validation Error",
                            "value": {
                                "reason": "VALIDATION_ERROR",
                                "message": "Invalid task schema",
                                "details": [{"loc": ["name"], "msg": "field required", "type": "value_error.missing"}],
                            },
                        },
                        "task_exists": {"summary": "Task Already Exists", "value": {"detail": "Task already exists."}},
                    }
                }
            },
        },
        500: {
            "description": "Internal server error occurred while processing the request.",
            "content": {"application/json": {"example": {"detail": "An unexpected error occurred. Please try again later."}}},
        },
    },
)
async def add_task(
    schema: UploadFile,
    repository: Repository = Depends(get_repository),  # noqa: B008
) -> JSONResponse:
    """
    Register a new task by uploading a task schema file. The file can be in JSON or YAML format.

    Args:
        schema (UploadFile): The task schema file to be uploaded.
        repository (Repository): The repository dependency for interacting with the task registry.

    Returns:
        JSONResponse: A response with a success message and the task ID.

    Raises:
        HTTPException: Raised if the file type is invalid, schema validation fails, or the task already exists.
    """
    try:
        # Validate file type
        if schema.content_type not in ["application/json", "text/yaml"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type, only JSON and YAML files are allowed.",
            )

        # Read and parse the schema content
        content = await schema.read()
        task_schema = safe_yaml_load(content) if schema.content_type == "text/yaml" else json.loads(content)
        task_model = Task.model_validate(task_schema)

        # Create and store the task in the repository
        await repository.create(
            id=task_model.id,
            name=task_model.name,
            description=task_model.description,
            schema=task_schema,
            type=SchemaType.TASK,
        )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"message": "Task registered successfully", "id": task_model.id},
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON file. Please provide a valid JSON file.",
        ) from None
    except InvalidYamlException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid YAML file. Please provide a valid YAML file.",
        ) from None
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "reason": "VALIDATION_ERROR",
                "message": "Invalid task schema",
                "details": err.errors(),
            },
        ) from None
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task already exists.",
        ) from None


@router.post(
    "/run",
    response_model=RunResult,
    tags=["Tasks"],
    description="Execute a specified task using the provided parameters. The task must already exist in the registry.",
    summary="Execute Task",
    responses={
        200: {
            "description": "Task executed successfully.",
            "content": {"application/json": {"example": {"id": "run_id"}}},
        },
        404: {
            "description": "Task not found in the registry.",
            "content": {"application/json": {"example": {"detail": "Task not found. Please provide a valid task ID."}}},
        },
    },
)
async def run_task(
    request: TaskRequest,
    repository: Repository = Depends(get_repository),  # noqa: B008
) -> RunResult:
    """
    Execute a task based on its ID and the provided parameters.

    Args:
        request (TaskRequest): The request body containing task ID, parameters, owner ID, and optionally, a parent task ID.
        repository (Repository): Dependency that provides access to the task registry.

    Returns:
        RunResult: The result of the task execution, including status and output.

    Raises:
        HTTPException: Raised if the task ID is not found in the registry.
    """
    try:
        # Retrieve the task by ID
        task = await repository.get_by_id(request.id)
        if task is None:
            raise repository.ItemNotFoundError

        result = celery.send_task(
            name="task_runner",
            kwargs={
                "schema": task.schema,
                "owner_id": request.owner_id,
                "parent_id": request.parent_id,
                "parameters": request.parameters,
            },
        )

        return RunResult(result.id)

    except repository.ItemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found. Please provide a valid task ID.",
        ) from None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while running the task. Please try again later.",
        ) from e
