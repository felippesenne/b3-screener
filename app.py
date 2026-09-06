from pathlib import Path
import runpy

from strategy_visuals import install_strategy_visuals

install_strategy_visuals()
runpy.run_path(str(Path(__file__).with_name("app_core.py")), run_name="__main__")
