from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pdf_merge_tool.app import run


if __name__ == "__main__":
    run()
