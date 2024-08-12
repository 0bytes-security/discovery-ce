import asyncio
import importlib
import os
from dataclasses import asdict
from typing import Callable, Type

from celery import Task

from discovery.core.celery import celery
from discovery.core.logger import logger
from discovery.runs.run import DefaultParameters, Run


class Registry:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.tasks: list[str] = []
        self.tasks_info: dict[str, tuple] = {}
        try:
            self.find_tasks()
            self.register_discovered_tasks()
        except Exception as e:
            logger.error(f"Failed to initialize Registry: {e}")
            raise

    def find_tasks(self) -> None:
        """Dynamically discover tasks from the discovery.tasks directory."""
        package_name = "discovery.tasks"
        try:
            package = importlib.import_module(package_name)
            package_path = getattr(package, "__path__", [None])[0]
        except ImportError as e:
            logger.error(f"Failed to import package {package_name}: {e}")
            return

        if package_path is None:
            logger.error("Could not find tasks path")
            return

        logger.info(f"Discovering tasks in {package_path}...")
        self._search_package(package_name, package_path)

    def _search_package(self, package_name: str, package_path: str) -> None:
        """Recursively search the package directory for task modules."""
        for filename in os.listdir(package_path):
            file_path = os.path.join(package_path, filename)
            if os.path.isdir(file_path):
                self._search_package(f"{package_name}.{filename}", file_path)
            elif filename.endswith(".py") and filename != "__init__.py":
                task_full_name = f"{package_name}.{filename[:-3]}"  # Remove '.py'
                self.tasks.append(task_full_name)
                logger.info(f"Discovered task module: {task_full_name}")

    def register_discovered_tasks(self):
        """Register the discovered tasks with Celery."""
        for task_name in self.tasks:
            try:
                task = self._create_task_wrapper(task_name)
                celery.task(name=task_name, bind=True)(task)
                logger.info(f"Registered task: {task_name} with Celery.")
            except Exception as e:
                logger.error(f"Failed to register task {task_name}: {e}")

    def _create_task_wrapper(self, task_name: str) -> Callable:
        module = self._import_task_module(task_name)

        def task_wrapper(task_instance: Task, **kwargs):
            task = module(task=task_instance)
            task.validate_parameters(**kwargs)
            result = asyncio.run(task.run(**kwargs))
            return asdict(result)

        return task_wrapper

    def _import_task_module(self, task_name: str) -> Type[Run]:
        try:
            module = importlib.import_module(task_name)
            task_class = getattr(module, "Task", None)
            params_class = getattr(module, "Parameters", None)
            results_class = getattr(module, "Result", None)
            if not issubclass(task_class, Run):
                raise RuntimeError(f"Module {task_name} is not a valid Task class.")
            if type(params_class) != type(DefaultParameters):  # noqa: E721
                raise RuntimeError(
                    f"Module {task_name} does not have a valid Parameters class."
                )
            if results_class is None:
                raise RuntimeError(
                    f"Module {task_name} does not have a valid Result class."
                )
            self.tasks_info[task_name] = (params_class, results_class)
            return task_class
        except (ImportError, KeyError, RuntimeError) as err:
            logger.error(f"Failed to import or validate task module {task_name}: {err}")
            raise RuntimeError(f"Failed to import task {task_name}") from err


registry = Registry()
