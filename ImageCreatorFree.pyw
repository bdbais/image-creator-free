# -*- coding: utf-8 -*-
"""Punto di ingresso senza console per PyInstaller."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from imagecreator.app import main

if __name__ == "__main__":
    sys.exit(main())
