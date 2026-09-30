"""conftest de pruebas e2e: Identity, Audit, Market Data, Ledger, Accounts, Wallet y Gateway como servidores reales."""

from __future__ import annotations

import asyncio

import pytest

PORT_IDENTITY = 18081
PORT_AUDIT = 18083
PORT_MARKET_DATA = 18084
PORT_LEDGER = 18085
PORT_ACCOUNTS = 18086
PORT_WALLET = 18087
PORT_GATEWAY = 18080
ALL_PORTS = (
    PORT_GATEWAY,
    PORT_IDENTITY,
    PORT_AUDIT,
    PORT_MARKET_DATA,
    PORT_LEDGER,
    PORT_ACCOUNTS,
    PORT_WALLET,
)


async def _wait_port_free(port: int, timeout: float = 20.0) -> None:
    """Espera a que nadie escuche en `port` (apagado limpio de instancias previas)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return  # conexión rechazada → puerto libre
        else:
            await asyncio.sleep(0.2)
        if asyncio.get_running_loop().time() > deadline:
            raise RuntimeError(f"el puerto {port} no se liberó en {timeout}s")


@pytest.fixture
async def servers(clean_dbs: None) -> None:  # type: ignore[no-untyped-def]
    import contextlib

    import uvicorn
    from accounts.main import create_app as create_accounts
    from audit.main import create_app as create_audit
    from gateway.main import create_app as create_gateway
    from identity.main import create_app as create_identity
    from ledger.main import create_app as create_ledger
    from market_data.main import create_app as create_market_data
    from wallet.main import create_app as create_wallet

    for port in ALL_PORTS:
        await _wait_port_free(port)

    boots = [
        (create_identity(), PORT_IDENTITY),
        (create_audit(), PORT_AUDIT),
        (create_market_data(), PORT_MARKET_DATA),
        (create_ledger(), PORT_LEDGER),
        (create_accounts(), PORT_ACCOUNTS),
        (create_wallet(), PORT_WALLET),
        (create_gateway(), PORT_GATEWAY),
    ]
    running: list[tuple[uvicorn.Server, asyncio.Task[None]]] = []
    try:
        for app, port in boots:
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
            server = uvicorn.Server(config)
            task = asyncio.create_task(server.serve())
            for _ in range(150):
                if server.started:
                    break
                if task.done():
                    task.result()  # propaga la excepción real de arranque
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError(f"servicio en puerto {port} no arrancó en 15s")
            running.append((server, task))
        yield
    finally:
        for server, _task in running:
            server.should_exit = True
        for _server, task in running:
            try:
                await asyncio.wait_for(task, timeout=10)
            except TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        for port in ALL_PORTS:
            with contextlib.suppress(RuntimeError):
                await _wait_port_free(port, timeout=15)
