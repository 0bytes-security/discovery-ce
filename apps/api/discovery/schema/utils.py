from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Type, Union

from pydantic import BaseModel, Field, create_model


class InvalidJSONSchema(ValueError):
    """Invalid JSON Schema."""

    def __init__(self, message: str):
        super().__init__(message)


class JSONSchemaToPydanticModel:
    def __init__(
        self,
        json_schema: Dict[str, Any],
    ):
        self.class_name: str = json_schema.get("title", "Model")
        self.raw_fields: Dict[str, Any] = json_schema.get("properties")
        self.required_fields: Set[str] = set(json_schema.get("required", []))
        self.model_fields: Dict[str, Tuple[Type, Field]] = {}

    def make(self) -> Type[BaseModel]:
        """
        Converts the JSON schema to a Pydantic BaseModel class.

        Returns:
            A Pydantic BaseModel class.
        """
        for field in self.raw_fields:
            self.model_fields[field] = self._create_field(field)

        return create_model(self.class_name, **self.model_fields)

    def _create_field(self, field: str) -> Tuple[Type, Field]:
        """
        Creates a Pydantic field based on the property schema.

        Args:
            field: The field name.
        Returns:
            A tuple containing the field type and the Field instance.
        """
        prop_schema = self.raw_fields.get(field)
        field_type = JSONSchemaToPydanticModel._resolve_type(prop_schema)
        default = ... if field in self.required_fields else prop_schema.get("default")
        return field_type, Field(
            description=prop_schema.get("description"),
            examples=prop_schema.get("examples"),
            default=default,
        )

    @staticmethod
    def _resolve_type(
        prop_schema: Dict[str, Any],
    ) -> Union[
        Type[int],
        Type[float],
        Type[bool],
        Type[Any],
        Type[None],
        Type[List],
        Type[Dict],
        Type[str],
        Any,
    ]:  # noqa: E501
        """
        Resolves the type of a property schema.

        Args:
            prop_schema (Dict[str, Any]): The property schema.

        Returns:
            Union[Type[int], Type[float], Type[bool], Type[Any], Type[None], Type[List], Type[Dict], Type[str], Any]: The corresponding Pydantic type.

        Raises:
            InvalidJSONSchema: If the type is not specified in the JSON schema.
        """  # noqa: E501
        schema_type = prop_schema.get("type")
        if schema_type is None:
            raise InvalidJSONSchema("Type not specified in the JSON schema.")

        if schema_type == "string":
            return JSONSchemaToPydanticModel._handle_string_type(prop_schema)
        elif schema_type == "integer":
            return int
        elif schema_type == "number":
            return float
        elif schema_type == "boolean":
            return bool
        elif schema_type == "array":
            return JSONSchemaToPydanticModel._handle_array_type(prop_schema)
        elif schema_type == "object":
            return JSONSchemaToPydanticModel._handle_object_type(prop_schema)
        elif schema_type == "null":
            return Optional[Any]
        else:
            raise InvalidJSONSchema(f"Invalid JSON schema: {prop_schema}")

    @staticmethod
    def _handle_string_type(prop_schema: Dict[str, Any]) -> Union[Type[str], List[str]]:
        """
        Handles the conversion of a JSON string type.

        Args:
            prop_schema: The property schema.

        Returns:
            str if the type is a string, otherwise a Literal type with the specified enum values.
        """  # noqa: E501
        if "enum" in prop_schema:
            return Literal[tuple(prop_schema["enum"])]  # type: ignore
        return str

    @staticmethod
    def _handle_array_type(prop_schema: Dict[str, Any]) -> List[Type[Any]]:
        """
        Handles the conversion of a JSON array type.

        Args:
            prop_schema: The property schema.

        Returns:
            A list of types.
        """
        items_schema = prop_schema.get("items")
        if not items_schema:
            raise InvalidJSONSchema("Array type must have an 'items' schema.")
        item_type = JSONSchemaToPydanticModel._resolve_type(items_schema)
        return List[item_type]

    @staticmethod
    def _handle_object_type(prop_schema: Dict[str, Dict[str, Any]]) -> Type[BaseModel]:
        """
        Handles the conversion of a JSON object type.

        Args:
            prop_schema: The property schema of type Dict[str, Dict[str, Any]].

        Returns:
            The corresponding Pydantic model type of type Type[BaseModel].
        """
        properties = prop_schema.get("properties")
        if not properties:
            return Dict[str, Any]
        return JSONSchemaToPydanticModel(prop_schema).make()
