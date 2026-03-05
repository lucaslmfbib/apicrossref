#!/usr/bin/env python3
"""Wrapper CLI para manter compatibilidade com o nome original do script."""

from __future__ import annotations

import sys

from crossref_client import main


if __name__ == "__main__":
    sys.exit(main())
