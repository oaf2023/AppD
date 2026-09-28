"""platform-kernel — núcleo compartido de todos los servicios."""

import sys

__version__ = "0.1.0"

if sys.platform == "win32":
    # psycopg (PostgreSQL async) no admite el ProactorEventLoop de Windows;
    # se fuerza el SelectorEventLoop en todas las entradas (servicios, CLI, tests).
    # Ver: docs/adr/ADR-0005-base-de-datos-por-servicio.md
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
