from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.safety.data.repository import SafetyRepository
from app.modules.safety.domain.interfaces.repository import ISafetyRepository


def get_safety_repo(db: Session = Depends(get_db)) -> ISafetyRepository:
    return SafetyRepository(db)
