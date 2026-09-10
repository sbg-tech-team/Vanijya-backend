from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.post.data.repository import PostRepository
from app.modules.post.domain.interfaces.repository import IPostRepository


def get_post_repo(db: Session = Depends(get_db)) -> IPostRepository:
    return PostRepository(db)
