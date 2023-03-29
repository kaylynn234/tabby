from asyncpg import Connection, Pool
from asyncpg.pool import PoolConnectionProxy
from contextvars import ContextVar


_CONNECTION: ContextVar[PoolConnectionProxy] = ContextVar("connection")


class Acquire:
    """A helper for acquiring database connections.

    This type is intended for use within an asynchronous context manager. If a connection to the database has not
    already been acquired, this type will acquire one and make it available in the current context. If a connection
    already exists within the current context, it is reused.
    """

    _pool: Pool
    _connection: PoolConnectionProxy | None
    _needs_cleanup: bool

    def __init__(self, *, pool: Pool) -> None:
        self._pool = pool
        self._connection = None
        self._needs_cleanup = False

    async def __aenter__(self) -> Connection:
        connection = _CONNECTION.get(None)

        if connection is None:
            connection = await self._pool.acquire()
            self._needs_cleanup = True

            _CONNECTION.set(connection)

        # Technically this is a lie - we return a `PoolConnectionProxy`, not a `Connection` - but `PoolConnectionProxy`
        # is usable as a `Connection`, by way of forwarding attribute lookups to a wrapped `Connection` object. Lying in
        # our type annotations like this gives us better completions at the call site, which is mostly what we care
        # about. But it is unfortunate that we need to do something like this in the first place.
        return connection  # type: ignore

    async def __aexit__(self, *_):
        assert self._connection is not None

        if self._needs_cleanup:
            await self._pool.release(self._connection)
