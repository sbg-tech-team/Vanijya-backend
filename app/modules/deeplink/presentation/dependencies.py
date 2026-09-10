from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.deeplink.data.repository import DeepLinkRepository
from app.modules.deeplink.domain.interfaces.repository import IDeepLinkRepository


def get_deeplink_repo(db: Session = Depends(get_db)) -> IDeepLinkRepository:
    return DeepLinkRepository(db)
