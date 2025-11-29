from typing import Any, Dict, List

from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    """A single task item."""

    id: str = Field(description="Unique identifier for the task")
    content: str = Field(description="Description of the task")
    status: str = Field(description="Status: pending, in_progress, completed, cancelled")


class TodoList(BaseModel):
    """List of tasks."""

    todos: List[TodoItem]


_todos: List[Dict[str, Any]] = []


def todo_write(
    todos: List[Dict[str, Any]],
    merge: bool = True,
) -> str:
    """
    Create and manage a structured task list.

    Args:
        todos: List of todo items. Each item should have 'id', 'content', and 'status'.
        merge: Whether to merge with existing todos (default True) or replace them.

    Returns:
        Current state of the todo list.
    """
    global _todos

    if not merge:
        _todos = todos
    else:
        # Merge logic
        todo_map = {t["id"]: t for t in _todos}
        for new_todo in todos:
            todo_map[new_todo["id"]] = new_todo
        _todos = list(todo_map.values())

    # Format output
    output = "Current Todo List:\n"
    for todo in _todos:
        status_icon = "[ ]"
        if todo.get("status") == "completed":
            status_icon = "[x]"
        elif todo.get("status") == "in_progress":
            status_icon = "[/]"
        elif todo.get("status") == "cancelled":
            status_icon = "[-]"

        output += f"{status_icon} {todo.get('id')}: {todo.get('content')}\n"

    return output
