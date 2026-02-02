import sys
import importlib
import types


def test_init_backend_import_defaults():
    """Import the module with external deps stubbed and assert defaults."""
    # Ensure repo src is importable
    sys.path.insert(0, "ITBench-SRE-Agent/src")

    # Stub external dependencies to keep import-time deterministic
    sys.modules.setdefault('crewai', types.ModuleType('crewai'))
    setattr(sys.modules['crewai'], 'LLM', lambda *a, **k: None)

    sys.modules.setdefault('lumyn.llm_backends.litellm_backend', types.ModuleType('lumyn.llm_backends.litellm_backend'))
    setattr(sys.modules['lumyn.llm_backends.litellm_backend'], 'LiteLLMBackend', lambda *a, **k: None)

    mod = importlib.import_module('lumyn.llm_backends.init_backend')

    # Verify variables exist and have safe defaults
    assert hasattr(mod, 'PROVIDER_AGENTS')
    assert mod.PROVIDER_AGENTS == ""
    assert hasattr(mod, 'PROVIDER_TOOLS')
    assert mod.PROVIDER_TOOLS == ""
    assert hasattr(mod, 'TEMPERATURE_AGENTS')
    assert isinstance(mod.TEMPERATURE_AGENTS, float)
    assert mod.TEMPERATURE_AGENTS == 0.0
