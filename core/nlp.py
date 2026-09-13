"""Compatibilidad retroactiva.

El parser actual vive en `core.command_parser`.
Este modulo queda como shim para no romper imports antiguos.
"""

from core.command_parser import (  # noqa: F401
    CommandAction,
    CommandInterpretation,
    CommandParser,
    interpret_command,
    set_default_parser,
)
