"""loop_factory — bucle de eventos compatible con psycopg async en Windows.

uvicorn >= 0.54 devuelve ``asyncio.ProactorEventLoop`` en Windows (``asyncio_loop_factory``),
que psycopg rechaza para su modo async. Se expone esta factory para usarla como cadena de
importación en ``uvicorn.run(loop=...)`` / ``--loop`` y garantizar ``SelectorEventLoop``
en todas las plataformas.

Uso: ``uvicorn.run(..., loop="platform_kernel.loop_factory:selector_loop_factory")``
"""

from __future__ import annotations

import asyncio


def selector_loop_factory(use_subprocess: bool = False) -> asyncio.AbstractEventLoop:
    """Devuelve una instancia de ``SelectorEventLoop`` (llamada sin argumentos por uvicorn)."""
    del use_subprocess  # firma compatible con el estilo ``*_loop_factory`` de uvicorn
    return asyncio.SelectorEventLoop()


__all__ = ["selector_loop_factory"]
