"""The same guard as tests/conftest.py: a test of this folder that ends with the working directory, the file-mode
mask or the subreaper setting of its process changed fails by name."""
from tests.conftest import process_state_guard  # noqa: F401  (autouse fixture)
