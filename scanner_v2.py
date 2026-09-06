from __future__ import annotations

import importlib
import scanner as _scanner

# Streamlit pode manter módulos importados em memória durante hot-reload.
# Recarregar explicitamente garante que app.py e scanner.py usem a mesma versão.
_scanner = importlib.reload(_scanner)

describe_strategy = _scanner.describe_strategy
scan_universe = _scanner.scan_universe
