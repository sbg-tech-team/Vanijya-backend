# entities.py defines what things ARE in pure Python. No database. No HTTP. Just shapes of data that the rest of the codebase agrees on.

#The domain/ folder should be able to run with nothing installed except Python itself.


# these are all the things that the server will have to sent in the response in the database
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

class ConvStatus:
    REQUESTED='requested'
    ACTIVE="active"
    BLOCKED="blocked"


#what a chat app needs for a user , his avatar , name , -- profile basically 
@dataclass
class UserSnap:
    user_id:UUID
    profile_id:int
    name:str
    is_user_verified:bool
    is_business_verified:bool 
    avatar_url:str | None
    role:str
    is_online:bool


# when we see the conversations list in the chats page each user will have their last message there -- now the usersnap has all the user info -- we just need the last message and when it sen hting htere
# we dont need to repet things from the user snap here 
@dataclass
class DMLastMessage:
    id:UUID  #this is the message id or convo id 
    body:Optional[str]
    message_type: str
    sender_id: UUID
    sent_at: datetime

@dataclass
class GroupLastMessage:
    id:UUID
    sender_id:UUID
    sender_name:str
    body:Optional[str]
    message_type:str
    sent_at:datetime

# the chat list that we see all the users with pending chats and all that - the entry to the chat module 
@dataclass
class ConversationEntity:
    id:UUID
    status:str #ConvStatus values
    initiator_id:Optional[UUID]
    participant:UserSnap
    last_message:Optional[DMLastMessage] 
    unread_count:int
    is_muted:bool
    created_at:datetime
    updated_at:datetime


@dataclass
class GroupConversationEntity:
    id:UUID
    group_name:str
    group_avatar:str | None
    member_count:int
    last_message:Optional[GroupLastMessage] 
    unread_count:int
    is_muted:bool
    created_at:datetime
    updated_at:datetime


#DEALs added in the group and the chats 
# now we need constant classes and a dealsnap to send to frontend to send only nessecery data that the frontend needs 

class PriceType:
    FIXED="fixed"
    NEGOTIABLE="negotiable"

class QuantityUnit:
    MT="MT"
    QUINTAL="quintal"


#  the snap is basically to show what to send to frontend 
class PostCategory:
    MARKET_UPDATE="Market Update"
    KNOWLEDGE="Knowledge"
    DISCUSSION="Discussion"
    DEAL_REQ="Deal/Requirements"

#For sharing a post in dm or a group chat
@dataclass
class PostSnap:
    post_id:int
    title:str
    image_urls: Optional[list[str]]
    caption:str
    category_id:int
    category_name:str
    author_name:str
    #need to add author_avatar_url too 
    # and a follow button if needed     


@dataclass
class DealSnap:
    deal_id: UUID
    deal_type: str                        # selling | buying
    title: str
    commodity_name: str
    grain_type: str
    grain_size: Optional[str]
    broken_percentage: Optional[float]
    commodity_quantity: float
    quantity_unit: str
    commodity_price: Optional[float]      # None for buying deals
    price_type: Optional[str]
    location: Optional[str]
    image_urls: Optional[list[str]]
    is_closed: bool
    caption: str


# the chat screen - here users are chatting with each other and this is the data carried by each chat 

    
@dataclass
class MessageEntity:
    id: UUID
    context_id: UUID
    context_type: str
    sender: UserSnap
    message_type: str
    body: Optional[str]
    media_urls: Optional[list[str]]
    media_metadata: Optional[dict]
    location_lat: Optional[float]
    location_lon: Optional[float]
    reply_to_id: Optional[UUID]
    is_deleted: bool
    sent_at: datetime
    deal:Optional[DealSnap]
    post:Optional[PostSnap]

@dataclass
class ConvSendGuard:
    """Lightweight result from get_conv_send_info — only what send_message needs."""
    status: str
    initiator_id: Optional[UUID]
    receiver_id: UUID
    sender_snap: UserSnap


