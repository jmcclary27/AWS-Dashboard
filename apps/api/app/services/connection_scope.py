from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Connection


class ConnectionSelectionError(ValueError):
    pass


def resolve_connection(session: Session, connection_id: int | None) -> Connection:
    if connection_id is not None:
        connection = session.get(Connection, connection_id)
        if not connection:
            raise ConnectionSelectionError("Connection not found")
        return connection

    enabled_connections = list(
        session.scalars(select(Connection).where(Connection.enabled.is_(True)).order_by(Connection.id)).all()
    )
    non_demo_enabled = [connection for connection in enabled_connections if connection.kind != "demo"]

    if len(non_demo_enabled) == 1:
        return non_demo_enabled[0]
    if len(non_demo_enabled) > 1:
        raise ConnectionSelectionError("Multiple enabled connections exist. Provide connection_id.")
    if len(enabled_connections) == 1:
        return enabled_connections[0]

    demo_connection = session.execute(
        select(Connection).where(Connection.kind == "demo").order_by(Connection.id)
    ).scalar_one_or_none()
    if demo_connection:
        return demo_connection

    raise ConnectionSelectionError("No available connection")
