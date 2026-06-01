"""Semantic AI System API package.

Replaces the monolithic api.py.  Splits endpoints into api/endpoints/*.py,
shared state into api/dependencies.py, and Pydantic models into api/models/*.py.

All module-level state (``_kg``, ``_tms``, ``_jepa``, etc.) and the FastAPI
``app`` live in ``api.dependencies``.  This ``__init__.py`` uses a custom
module class so that ``api._kg`` always resolves to the canonical value in
``api.dependencies._kg``, preserving backward compatibility with tests that do::

    api._kg = KnowledgeGraph()   # forwarded to api.dependencies._kg
"""

import sys
import types


class _ApiModule(types.ModuleType):
    """Proxies attribute get/set/del to ``api.dependencies``.

    This lets test code written as ``api._kg = X`` transparently update
    ``api.dependencies._kg`` so that endpoint modules (which import from
    ``api.dependencies``) see the same value.
    """

    # Names that belong to the api package namespace itself (set on __dict__
    # directly, never forwarded to api.dependencies).
    _LOCAL_NAMES = frozenset({
        "dependencies", "endpoints", "models", "core",
        "__class__", "__name__", "__file__", "__path__", "__spec__",
        "__loader__", "__package__", "__doc__", "__builtins__",
    })

    def __getattr__(self, name):
        if name in self._LOCAL_NAMES:
            raise AttributeError(name)
        import api.dependencies
        return getattr(api.dependencies, name)

    def __setattr__(self, name, value):
        if name in self._LOCAL_NAMES:
            super().__setattr__(name, value)
            return
        import api.dependencies
        setattr(api.dependencies, name, value)

    def __delattr__(self, name):
        if name in self._LOCAL_NAMES:
            super().__delattr__(name)
            return
        import api.dependencies
        delattr(api.dependencies, name)


sys.modules[__name__].__class__ = _ApiModule

# Bootstrap by importing dependencies.  This initialises all globals (``_kg``,
# ``_tms``, ``_jepa``, …), creates the FastAPI ``app``, registers the lifespan,
# includes all endpoint routers, and applies middleware.
import api.dependencies  # noqa: F401, E402
