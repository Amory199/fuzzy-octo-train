"""Workflow DSL (Domain-Specific Language) parser for YAML/JSON definitions.

Allows defining workflows declaratively using YAML or JSON files.

Example YAML workflow:
```yaml
name: ETL Pipeline
metadata:
  owner: data-team
  environment: production

tasks:
  - name: extract
    timeout: 30.0
    retry_count: 3
    priority: 10

  - name: validate
    depends_on:
      - extract
    timeout: 10.0

  - name: transform
    depends_on:
      - validate
    priority: 5

  - name: load
    depends_on:
      - transform
    timeout: 60.0
```

Usage:
    from flowmesh.dsl import WorkflowParser

    parser = WorkflowParser()
    workflow = parser.parse_file("pipeline.yaml")
    engine = ExecutionEngine()
    results = await engine.execute(workflow)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from flowmesh.core.models import Task, Workflow

logger = logging.getLogger(__name__)


class WorkflowParser:
    """Parse workflow definitions from YAML or JSON files.

    Converts declarative workflow definitions into Workflow objects
    that can be executed by the ExecutionEngine.
    """

    def __init__(self) -> None:
        self._task_registry: dict[str, Any] = {}

    def register_task(self, name: str, func: Any) -> None:
        """Register a task function that can be referenced in workflows.

        Args:
            name: Task name to use in workflow definitions
            func: Async callable to execute for this task

        Example:
            parser = WorkflowParser()

            async def extract_data():
                return {"records": 1000}

            parser.register_task("extract", extract_data)
        """
        self._task_registry[name] = func
        logger.debug(f"Registered task function: {name}")

    def parse_file(self, filepath: str | Path) -> Workflow:
        """Parse a workflow from a YAML or JSON file.

        Args:
            filepath: Path to workflow definition file

        Returns:
            Parsed Workflow object ready for execution

        Raises:
            ValueError: If file format is invalid or required fields are missing
            FileNotFoundError: If file doesn't exist
        """
        path = Path(filepath)

        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {filepath}")

        content = path.read_text()

        if path.suffix in [".yaml", ".yml"]:
            return self.parse_yaml(content)
        elif path.suffix == ".json":
            return self.parse_json(content)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}. Use .yaml, .yml, or .json")

    def parse_yaml(self, yaml_content: str) -> Workflow:
        """Parse a workflow from YAML string.

        Args:
            yaml_content: YAML workflow definition

        Returns:
            Parsed Workflow object

        Raises:
            ImportError: If PyYAML is not installed
            ValueError: If YAML is invalid
        """
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("PyYAML not installed. Install with: pip install pyyaml") from exc

        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc

        return self._parse_dict(data)

    def parse_json(self, json_content: str) -> Workflow:
        """Parse a workflow from JSON string.

        Args:
            json_content: JSON workflow definition

        Returns:
            Parsed Workflow object

        Raises:
            ValueError: If JSON is invalid
        """
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        return self._parse_dict(data)

    def _parse_dict(self, data: dict[str, Any]) -> Workflow:
        """Parse workflow from dictionary.

        Args:
            data: Workflow definition dictionary

        Returns:
            Parsed Workflow object

        Raises:
            ValueError: If required fields are missing or invalid
        """
        # Validate required fields
        if "name" not in data:
            raise ValueError("Workflow 'name' is required")

        if "tasks" not in data or not data["tasks"]:
            raise ValueError("Workflow must have at least one task")

        name = data["name"]
        metadata = data.get("metadata", {})

        # Parse tasks
        tasks = []
        for task_data in data["tasks"]:
            task = self._parse_task(task_data)
            tasks.append(task)

        workflow = Workflow(name=name, tasks=tasks, metadata=metadata)

        logger.info(f"Parsed workflow '{name}' with {len(tasks)} tasks")
        return workflow

    def _parse_task(self, task_data: dict[str, Any]) -> Task:
        """Parse a single task from dictionary.

        Args:
            task_data: Task definition dictionary

        Returns:
            Parsed Task object

        Raises:
            ValueError: If required fields are missing or task function not registered
        """
        if "name" not in task_data:
            raise ValueError("Task 'name' is required")

        name = task_data["name"]

        # Get task function from registry or use noop
        if name in self._task_registry:
            func = self._task_registry[name]
        else:
            logger.warning(
                f"Task '{name}' not registered, using noop function. "
                f"Register with parser.register_task('{name}', your_func)"
            )

            async def _noop() -> None:
                pass

            func = _noop

        # Parse optional fields
        depends_on = task_data.get("depends_on", [])
        timeout_seconds = task_data.get("timeout", 300.0)
        retry_count = task_data.get("retry_count", 0)
        priority = task_data.get("priority", 0)
        metadata = task_data.get("metadata", {})

        # Parse input_map if present
        input_map = task_data.get("input_map", {})

        # Parse condition if present (only supported in programmatic mode)
        condition = task_data.get("condition")

        return Task(
            name=name,
            func=func,
            depends_on=depends_on,
            timeout_seconds=timeout_seconds,
            retry_count=retry_count,
            priority=priority,
            metadata=metadata,
            input_map=input_map,
            condition=condition,
        )

    def validate(self, data: dict[str, Any]) -> list[str]:
        """Validate workflow definition and return list of errors.

        Args:
            data: Workflow definition dictionary

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check required fields
        if "name" not in data:
            errors.append("Missing required field: 'name'")

        if "tasks" not in data:
            errors.append("Missing required field: 'tasks'")
        elif not isinstance(data["tasks"], list):
            errors.append("Field 'tasks' must be a list")
        elif len(data["tasks"]) == 0:
            errors.append("Workflow must have at least one task")

        # Validate tasks
        if "tasks" in data and isinstance(data["tasks"], list):
            task_names = set()
            for i, task in enumerate(data["tasks"]):
                if not isinstance(task, dict):
                    errors.append(f"Task at index {i} must be a dictionary")
                    continue

                if "name" not in task:
                    errors.append(f"Task at index {i} missing required field: 'name'")
                else:
                    task_name = task["name"]

                    # Check for duplicate names
                    if task_name in task_names:
                        errors.append(f"Duplicate task name: '{task_name}'")
                    task_names.add(task_name)

                    # Validate dependencies reference existing tasks
                    depends_on = task.get("depends_on", [])
                    for dep in depends_on:
                        if dep == task_name:
                            errors.append(f"Task '{task_name}' cannot depend on itself")

        return errors
