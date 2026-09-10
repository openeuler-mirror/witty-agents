#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.argv = ["nl2sql_skill_cli.py", "health", *sys.argv[1:]]
from nl2sql_skill_cli import main

main()
