from pydantic import BaseModel
from typing import Optional


class ShareLinkResponse(BaseModel):
    deep_link: str
    share_text: str
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
