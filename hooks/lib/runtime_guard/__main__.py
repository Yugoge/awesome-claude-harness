"""Package entry-point so `python -m lib.runtime_guard` still works."""
from ._core import main
raise SystemExit(main())
