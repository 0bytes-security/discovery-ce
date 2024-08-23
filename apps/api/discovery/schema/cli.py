import argparse
import json
from pathlib import Path
from typing import Literal

import yaml
from click import secho
from pydantic import ValidationError

from discovery.core import logger

VERSION = "1.0.0"


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Discovery Schema",
        prog="discovery-schema",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
        help="Show the version of the CLI tool",
    )
    # Schema Generate
    parser_generate = subparsers.add_parser("generate", help="Generate schema")
    parser_generate.add_argument(
        "-O",
        "--output",
        type=Path,
        required=True,
        help="Output path for the generated schema",
    )

    # Schema Validate
    parser_validate = subparsers.add_parser("validate", help="Validate schema")
    parser_validate.add_argument("-f", "--file", type=Path, help="Path to the schema file to validate")
    parser_validate.add_argument(
        "-t",
        "--type",
        type=str,
        choices=["workflow", "task", "auto"],
        required=False,
        default="auto",
        help="Schema type for validation, defaults to auto",
    )
    parser_validate.add_argument("--dir", type=Path, help="Directory containing schema files to validate")

    return parser.parse_args()


def generate_schema(output_path: Path) -> None:
    """Generate schema files and write to the specified output path."""
    from .tasks import Task
    from .workflows import Workflow

    if not output_path.exists():
        secho(f"Creating directory {output_path}", fg="yellow")
        output_path.mkdir(parents=True, exist_ok=True)
    elif not output_path.is_dir():
        raise ValueError("Output path is not a directory. Please specify a directory path.")

    paths = {
        "workflow": output_path / "workflow.schema.json",
        "task": output_path / "task.schema.json",
    }
    try:
        with open(paths["workflow"], "w") as file:
            json.dump(Workflow.model_json_schema(), file, indent=2)
            secho(f"Workflow schema written to {paths['workflow']}", fg="green")

        with open(paths["task"], "w") as file:
            json.dump(Task.model_json_schema(), file, indent=2)
            secho(f"Task schema written to {paths['task']}", fg="green")
    except OSError as e:
        secho(f"Failed to write schema: {e}", fg="red")
        exit(1)


def validate_schema_from_file(path: Path, schema_type: Literal["workflow", "task", "auto"]) -> None:
    """Validate a schema file based on its type."""
    try:
        if path.suffix == ".json":
            with open(path) as file:
                schema = json.load(file)
        elif path.suffix in [".yaml", ".yml"]:
            with open(path) as file:
                schema = yaml.safe_load(file)
        else:
            raise ValueError("Schema file extension must be .json, .yaml, or .yml")

        schema_type = str(path.stem.split(".")[-2]) if schema_type == "auto" else schema_type
        if schema_type == "workflow":
            from .workflows import Workflow

            Workflow.model_validate(obj=schema)
            secho(f"Workflow schema validation passed for {path.name}", fg="green")
        elif schema_type == "task":
            from .tasks import Task

            Task.model_validate(obj=schema)

            secho(
                f"Task schema validation passed for {path.name}",
                fg="green",
            )

        else:
            raise ValueError("Unable to auto-detect schema type, use --type to specify schema type.")
    except ValidationError as e:
        msg = f"Invalid schema in {path.name}"
        for error in e.errors():
            location = " -> ".join(map(str, error["loc"]))
            msg += f"\nLocation: {location}, Error: {error['msg']}"
        secho(f"{msg}", fg="red")


def validate_schema(schema_path: Path, schema_type: Literal["workflow", "task", "auto"]) -> None:
    """Validate schema files or all files in a directory."""
    if not schema_path.exists():
        raise ValueError(f"Schema file or directory {schema_path} does not exist.")

    if schema_type != "auto" and schema_path.is_dir():
        raise ValueError("Schema type must be 'auto' when validating a directory.")

    if schema_path.is_dir():
        files = (p.resolve() for p in schema_path.glob("**/*") if p.suffix in {".json", ".yaml", ".yml"})
        for file in files:
            secho(f"Validating schema file {file.name}", fg="yellow")
            validate_schema_from_file(file, schema_type)
    else:
        validate_schema_from_file(schema_path, schema_type)


def main() -> None:
    """Main function to execute CLI commands."""
    try:
        logger.setLevel(0)
        args = parse_arguments()

        if args.command == "generate":
            secho(f"Generating schema in {args.output}", fg="yellow")
            generate_schema(args.output)
        elif args.command == "validate":
            if args.file:
                secho(f"Validating schema file {args.file}", fg="yellow")
                validate_schema(args.file, args.type)
            elif args.dir:
                secho(
                    f"Validating schema directory {args.dir}",
                    fg="yellow",
                )
                validate_schema(args.dir, args.type)
            else:
                raise ValueError("Either --file or --dir must be specified for validation.")
    except ValueError as e:
        secho(str(e), fg="red")
        exit(1)


if __name__ == "__main__":
    main()
