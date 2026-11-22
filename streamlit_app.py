"""Streamlit's default main file: opens the newspaper (press/app.py)."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "press" / "app.py"), run_name="__main__")
