"""PyInstaller entry for the command line (``previously-on-cli.exe``) —
``check`` and ``snapshot`` are what a player is asked to run."""

import sys

from previously_on.cli import main

sys.exit(main())
