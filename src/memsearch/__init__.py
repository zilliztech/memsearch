"""memsearch — semantic memory search for markdown knowledge bases.

Example:
    >>> from memsearch import MemSearch
    >>> mem = MemSearch(paths=["./docs"])
    >>> await mem.index()
    >>> results = await mem.search("query")

See https://zilliztech.github.io/memsearch/ for full documentation.
"""

from .core import MemSearch

__version__ = "0.1.15"
__all__ = ["MemSearch", "__version__"]
