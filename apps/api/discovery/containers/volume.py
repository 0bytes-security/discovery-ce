import base64
import mimetypes
import shutil
from dataclasses import dataclass
from enum import Enum
from os import chown
from pathlib import Path
from typing import List, Optional, Union
from uuid import uuid4

from discovery.core.s3 import BUCKET_NAME, get_s3_client


class Mode(str, Enum):
    READ_WRITE = "rw"
    READ_ONLY = "ro"


@dataclass
class Volume:
    host: str
    guest: str
    mode: Mode


@dataclass
class File:
    name: str
    content: str
    content_type: Optional[str]


@dataclass
class S3File:
    path: str
    content_type: Optional[str]


DEFAULT_UNIX_PERMISSIONS = 0o750
DEFAULT_UID = 1000
DEFAULT_GID = 1000


class ContainerVolume:
    def __init__(self, base_path: str, mode: Mode = Mode.READ_WRITE, change_owner: bool = True) -> None:
        """Initialize a new ContainerVolume object.

        Args:
            base_path (str): The base path for volumes.
            mode (Mode, optional): The mode of the volume. Defaults to Mode.READ_WRITE.
            change_owner (bool, optional): Whether to change the owner of the volume.
            Defaults to True.
        """
        self._mode = mode
        self._id = str(uuid4())
        self._volume_path = self._create_volume(base_path, change_owner)

    def _create_volume(self, base_path: str, change_owner: bool) -> Path:
        """Create the volume directory and set permissions."""
        path = Path(f"{base_path}/{self._id}/runs")
        path.mkdir(mode=DEFAULT_UNIX_PERMISSIONS, parents=True)
        if change_owner:
            chown(path, DEFAULT_UID, DEFAULT_GID)
        return path

    def file_exists(self, path: str) -> bool:
        """Check if a file exists in the volume.

        Args:
            path (str): The path of the file.

        Returns:
            bool: True if the file exists, False otherwise.
        """
        return self._volume_path.joinpath(path).exists()

    def write(self, path: str, content: str) -> None:
        """Write content to a file in the volume.

        Args:
            path (str): The name of the file.
            content (str): The content to write.
        """
        try:
            with self._volume_path.joinpath(path).open("w") as file:
                file.write(content)
        except OSError as err:
            raise RuntimeError(f"Failed to write file {path}") from err

    def read(self, path: str, read_bytes: bool = False) -> Union[str, bytes]:
        """Read the content of a file in the volume.

        Args:
            path (str): The path of the file.
            read_bytes (bool, optional): Whether to read the content as bytes.
            Defaults to False.

        Returns:
            AnyStr: The content of the file.
        """
        try:
            mode = "rb" if read_bytes else "r"
            with self._volume_path.joinpath(path).open(mode) as file:
                return file.read()
        except OSError as err:
            raise RuntimeError(f"Failed to read file {path}") from err

    def make_dir(self, name: str) -> None:
        """Create a directory in the volume.

        Args:
            name (str): The name of the directory.
        """
        try:
            (self._volume_path / name).mkdir(mode=DEFAULT_UNIX_PERMISSIONS, parents=True)
        except OSError as err:
            raise RuntimeError(f"Failed to create directory {name}") from err

    @property
    def files(self) -> List[File]:
        """Returns a list of all files in the volume, with the file path as the key and
        the base64-encoded content
        as the value.

        Returns:
            List[File]: A list of File objects.
        """
        file_list = []
        for p in self._volume_path.rglob("*"):
            if p.is_file():
                try:
                    with p.open("rb") as file:
                        content = base64.b64encode(file.read()).decode("utf-8")
                    file_list.append(
                        File(
                            name=str(p.relative_to(self._volume_path)),
                            content=content,
                            content_type=mimetypes.guess_type(str(p))[0],
                        )
                    )
                except OSError as err:
                    raise RuntimeError(f"Failed to read file {p}") from err
        return file_list

    def upload_files_to_s3(self) -> List[S3File]:
        """Uploads files to S3 and returns a list of S3File objects.

        Returns:
            List[S3File]: A list of S3File objects containing the path and content type.
        """
        file_list = []
        s3 = get_s3_client()
        for p in self._volume_path.rglob("*"):
            if p.is_file():
                try:
                    upload_path = f"{self._id}/{p.relative_to(self._volume_path)}"
                    s3.Bucket(BUCKET_NAME).upload_file(str(p), upload_path)
                    file_list.append(
                        S3File(
                            path=upload_path,
                            content_type=mimetypes.guess_type(str(p))[0],
                        )
                    )
                except Exception as err:
                    raise RuntimeError(f"Failed to upload file {p} to S3") from err
        return file_list

    def mount(self) -> Volume:
        """Get the Volume object representing the volume.

        Returns:
            Volume: The Volume object.
        """
        return Volume(
            mode=self._mode,
            host=str(self._volume_path),
            guest=str(self._volume_path),
        )

    def cleanup(self) -> None:
        """Clean up the volume by removing the directory."""
        try:
            shutil.rmtree(self._volume_path)
        except OSError as err:
            raise RuntimeError(f"Failed to clean up volume {self._volume_path}") from err
