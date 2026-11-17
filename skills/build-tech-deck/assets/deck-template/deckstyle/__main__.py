"""`python -m deckstyle` 等同 `deckstyle` 命令。"""

import sys

from .cli import main

sys.exit(main())
