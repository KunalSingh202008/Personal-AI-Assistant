import sys
import unittest
from pathlib import Path

backend_dir = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend_dir))

loader = unittest.TestLoader()
suite = loader.discover(str(backend_dir / "tests"))
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
