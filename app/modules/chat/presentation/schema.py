### This is all the schema that the api endpoints accept and payload requirements --- like type check 
#so this is basically pydantic models 
from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field



#start a brand new dm with someone - for the first time 
class OpenChatRequest(BaseModel):
    participant_id:UUID
    first_message: str = Field(..., min_length=1, max_length=4000)


#fire every time -- in an existing dm 
class SendMessageRequest(BaseModel):
    body: Optional[str] =Field(None, max_length=4000)
    message_type: str = Field(default="text", pattern=r"^(text|image|video|document|audio|location|deal|post)$")
    media_urls: Optional[list[str]]  = None
    media_metadata: Optional[dict]  =None
    location_lat: Optional[float]  = None
    location_lon: Optional[float] =None
    reply_to_id: Optional[UUID]  =None
    deal_id: Optional[UUID] =None
    post_id: Optional[int] =None

    


class SendGroupMessageRequest(BaseModel):
    body: Optional[str] = Field(None, max_length=4000)
    message_type: str = Field(default="text", pattern=r"^(text|image|video|document|audio|location|deal|post)$")
    media_urls: Optional[list[str]] = None
    media_metadata: Optional[dict] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    reply_to_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    post_id: Optional[int] = None