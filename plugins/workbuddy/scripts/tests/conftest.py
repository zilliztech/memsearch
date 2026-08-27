"""pytest 引导：使 hooks/ 目录下的 handler/parse 可被 import。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
