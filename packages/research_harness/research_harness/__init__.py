__version__ = "1.5.0"

# Convenience re-exports so callers can do `from research_harness import ResearchAPI`
# instead of remembering `from research_harness.api import ResearchAPI`.
from ._productization import lg10_productization_boundary  # noqa: E402
from .api import ResearchAPI  # noqa: E402

__all__ = ["ResearchAPI", "__version__", "lg10_productization_boundary"]
