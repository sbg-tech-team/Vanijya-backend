from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.groups.data.repository import GroupsRepository
from app.modules.groups.domain.interfaces.repository import IGroupsRepository


def get_groups_repo(db: Session = Depends(get_db)) -> IGroupsRepository:
    return GroupsRepository(db)
