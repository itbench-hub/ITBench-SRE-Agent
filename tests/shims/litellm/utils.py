"""Minimal utils shim for the litellm test shim (moved under tests/shims).

Provides a `wrapper` decorator that simply returns the original function.
"""
from typing import Callable, Any

def wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
    if callable(func):
        return func

    def _decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        return f

    return _decorator
