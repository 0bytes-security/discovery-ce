from string import Template
from typing import (
    Any,
    Dict,
    Literal,
    NotRequired,
    Optional,
    Set,
    Tuple,
    Type,
    TypedDict,
)

from pydantic import BaseModel, Field, create_model, model_validator

from .utils import (
    JSONSchemaToPydanticModel,
)

SUPPORTED_FILE_TYPES = Literal["json", "jsonl", "csv", "txt"]


class ExtraParameter(BaseModel):
    file: bool = Field(..., description="Whether the parameter is a file.", alias="file")


class Parameter(BaseModel):
    description: str = Field(..., description="The description of the parameter.")
    parameterSchema: dict = Field(
        description="The schema of the parameter, if the parameter type is object or array.",
        example="{ 'type': 'object', 'properties': { 'foo': { 'type': 'string' } } }",
        alias="schema",
    )
    default: Optional[Any] = Field(None, description="The default value of the parameter.")
    is_file: Optional[bool] = Field(None, description="Whether the parameter is a file.", alias="is-file")
    file_type: Optional[SUPPORTED_FILE_TYPES] = Field(None, description="The file type.", alias="file-type")


class Output(BaseModel):
    description: str = Field(..., description="The description of the output.")
    outputSchema: dict = Field(
        description="The schema of the output, if applicable.",
        example=[
            "{ 'type': 'object', 'properties': { 'foo': { 'type': 'string' } } }",
            "{ 'type': 'array', 'items': { 'type': 'object', 'properties': { 'bar': { 'type': 'string' } } } }",
        ],
        alias="schema",
    )
    is_file: Optional[bool] = Field(None, description="Whether the output is a file.", alias="is-file")
    file_type: Optional[SUPPORTED_FILE_TYPES] = Field(None, description="The file type.", alias="file-type")


class CommandPlaceholder(TypedDict):
    type: Literal["INPUT", "OUTPUT"] = "INPUT"
    is_file: NotRequired[bool]
    file_type: NotRequired[SUPPORTED_FILE_TYPES]
    model: BaseModel


class Task(BaseModel):
    version: Optional[Literal["1.0"]] = Field("1.0", description="Task schema version.")
    id: str = Field(..., description="The identifier of the task.", pattern="^[a-z0-9-./]+$")
    name: Optional[str] = Field(None, description="The name of the task.")
    description: Optional[str] = Field(None, description="The description of the task.")
    image: str = Field(..., description="The image to use for the task.")
    parameters: Dict[str, Parameter] = Field(..., description="The parameters for the task.")
    command: str = Field(..., description="The command template for the task.", examples=["nmap $target"])
    outputs: Dict[str, Output] = Field(..., description="The outputs for the task.")
    _parsed_parameters: Optional[BaseModel] = None
    _parsed_outputs: Optional[BaseModel] = None
    _command_placeholders: Optional[Dict[str, CommandPlaceholder]] = None

    def _parameters_schema_to_pydantic(self) -> BaseModel:
        fields: Dict[str, Tuple[Type, Field]] = {}
        for key, parameter in self.parameters.items():
            fields[key] = (
                Optional[JSONSchemaToPydanticModel._resolve_type(parameter.parameterSchema)] if parameter.default else JSONSchemaToPydanticModel._resolve_type(parameter.parameterSchema),
                Field(description=parameter.description, default=parameter.default if parameter.default else ..., pattern=parameter.parameterSchema.get("pattern", None)),
            )
        return create_model("TaskParameters", **fields)

    def _outputs_schema_to_pydantic(self) -> BaseModel:
        fields: Dict[str, Tuple[Type, Field]] = {}
        for key, output in self.outputs.items():
            fields[key] = (
                JSONSchemaToPydanticModel._resolve_type(output.outputSchema),
                Field(description=output.description, pattern=output.outputSchema.get("pattern", None)),
            )
        return create_model("TaskOutputs", **fields)

    def validate_command(self) -> Dict[str, CommandPlaceholder]:
        """
        Validate the command placeholders.

        Returns:
            Dict[str, CommandPlaceholder]: A dictionary of command placeholders.
        """
        command_keys: Set[str] = set(Template(self.command).get_identifiers())

        parameter_keys: Set[str] = set(self.parameters.keys())
        output_keys: Set[str] = set(self.outputs.keys())
        # Remove RUN_DIR from command keys as it a defualt KEY
        command_keys.discard("RUN_DIR")
        invalid_keys: Set[str] = command_keys - (parameter_keys | output_keys)
        if invalid_keys:
            raise ValueError(f"Command contains placeholders that are not in the parameters or outputs: {invalid_keys}.")
        return {
            key: CommandPlaceholder(
                type="INPUT" if key in parameter_keys else "OUTPUT",
                is_file=(self.parameters.get(key) or self.outputs.get(key)).is_file,
                file_type=(self.parameters.get(key) or self.outputs.get(key)).file_type,
            )
            for key in command_keys
        }

    @model_validator(mode="after")
    def validate_task(self) -> "Task":
        """
        Validate the task.

        Returns:
            Task: The validated task object.
        """
        self._parsed_parameters: Type[BaseModel] = self._parameters_schema_to_pydantic()
        self._parsed_outputs: Type[BaseModel] = self._outputs_schema_to_pydantic()
        self._command_placeholders: Dict[str, CommandPlaceholder] = self.validate_command()
        return self

    def validate_parameters(self, params: Dict[str, str]) -> None:
        """Validate the parameters."""
        self._parsed_parameters.model_validate(obj=params)

    @property
    def validated_parameters_schema(self) -> BaseModel:
        """Get the validated parameters schema."""
        return self._parsed_parameters

    @property
    def validated_outputs_schema(self) -> BaseModel:
        """Get the validated outputs schema."""
        return self._parsed_outputs

    @property
    def command_placeholders(self) -> Dict[str, CommandPlaceholder]:
        """Get the command placeholders."""
        return self._command_placeholders
