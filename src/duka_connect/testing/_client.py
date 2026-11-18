"""A client of a simulated unit that spends little time on its silence."""
from event_connect import Clock

from .._client import Client
from .._duka import build_client
from ._simulator import SimulatedDuka


def client_for(unit: SimulatedDuka, *, timeout: float, attempts: int, clock: Clock,
               password: str | None = None, read_only: bool = False) -> Client:
    """A client of the started `unit`, as `create_client` makes one, but waiting `timeout` seconds
    for each of `attempts` sends of a request; with `password` in place of the unit's own where
    given."""
    return build_client(unit.host, unit.port, device_id=unit.device_id,
                        password=unit.password if password is None else password,
                        timeout=timeout, attempts=attempts, read_only=read_only, clock=clock)
