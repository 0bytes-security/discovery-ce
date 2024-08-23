from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from discovery.schema.tasks import Task


class Workflow(BaseModel):
    version: Literal["1.0"] = Field(..., description="Workflow schema version.")
    name: str = Field(..., description="Name of the workflow.")
    description: str = Field(..., description="Detailed description of the workflow.")
    runs: List[Task] = Field(..., description="List of tasks in the workflow.")
    variables: Dict[str, str] = Field(..., description="Required variables for the first run.")
