"""Puts src/ on the path so `import core.x` / `import analysis.x` / `import
automation.x` / `import strategies.x` resolve the same way for pytest as they
do for app.py, without touching any of those import statements."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
