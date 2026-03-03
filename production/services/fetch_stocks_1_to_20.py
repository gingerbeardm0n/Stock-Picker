#!/usr/bin/env python3
"""Backward-compatible wrapper for the renamed stock range fetcher."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.fetch_stocks_in_price_range import main


if __name__ == "__main__":
    main()
