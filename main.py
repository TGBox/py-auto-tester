#!/usr/bin/env python
"""
Startpunkt für die GUI, wenn das Paket nicht installiert ist
(z.B. Doppelklick oder `uv run python main.py`).

Bei installiertem Paket geht es kürzer:
    py-auto-tester gui
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from py_auto_tester.app import main

if __name__ == "__main__":
    sys.exit(main())
