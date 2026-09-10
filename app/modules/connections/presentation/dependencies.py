from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.connections.data.repository import ConnectionsRepository
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository


def get_connections_repo(db: Session = Depends(get_db)) -> IConnectionsRepository:
    return ConnectionsRepository(db)
