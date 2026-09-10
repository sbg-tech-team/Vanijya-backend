from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.profile.data.repository import ProfileRepository
from app.modules.profile.domain.interfaces.repository import IProfileRepository


def get_profile_repo(db: Session = Depends(get_db)) -> IProfileRepository:
    return ProfileRepository(db)
