# class DoSomethingUseCase:
#     def __init__(self, repo):
#         self.repo = repo          # store the repo, don't call it yet

#     def execute(self, ...):       # all the work happens here
#         # 1. validate rules
#         # 2. call repo methods
#         # 3. return result or raise error


# This is the value of writing use cases first. You're writing the code that consumes the repo, which tells you exactly what methods the repo must implement. When you go build data/repository.py next, you'll know precisely what functions to write — because the use cases are already calling them.


from fastapi import HTTPException 
from datetime import datetime
from typing import Optional
from uuid import UUID
from app.modules.chat.domain.entities import ConvStatus

class GetConversationsUseCase:
    def __init__(self,repo):
        self.repo=repo


    def execute(self,user_id:UUID,page:int=1,per_page:int=20,):
        return self.repo.get_conversations(user_id,page,per_page)
    

class MarkReadUseCase:
    def __init__(self,repo):
        self.repo=repo
       
    def execute(self,user_id:UUID,conv_id:UUID):
        if not self.repo.is_member(conv_id,user_id):
             #gaurd clause -- reject the bad cases early 
            raise HTTPException(status_code=403,detail="the user is not a part of this convo")    
        return self.repo.mark_read(conv_id,user_id)


class GetMessagesUseCase:
    def __init__(self,repo):
        self.repo=repo

    def execute(self,user_id:UUID,conv_id:UUID,before:Optional[datetime]=None,limit:int=50):  #here 50 value is defalut not a constant so if no limit is passes we will send 50 
        if not self.repo.is_member(conv_id,user_id):
            raise HTTPException(status_code=403,detail="the user is not a part of this convo")    
        return self.repo.get_messages("dm",conv_id,before,min(limit,100))  # here we use min due to have an block to 100 msg only 
    


class AcceptConversationUseCase: 
    def __init__(self,repo):
        self.repo=repo

    def execute(self,user_id:UUID,conv_id:UUID):
        conv=self.repo.get_conversation(conv_id,user_id)
        if not conv :
             raise HTTPException(status_code=404,detail="no conversations ")
        if conv.status != ConvStatus.REQUESTED:
            raise HTTPException(status_code=409 , detail=f"cannot accept : conversation already - '{conv.status}.'")
        return self.repo.set_conversation_status(conv_id, ConvStatus.ACTIVE, user_id)
    
class DeclineConversationUseCase:
    def __init__(self,repo):
        self.repo=repo

    def execute(self,user_id:UUID,conv_id:UUID):
        converstaion=self.repo.get_conversation(conv_id,user_id)
        if not converstaion :
             raise HTTPException(status_code=404,detail="no conversations ")
        if converstaion.status != ConvStatus.REQUESTED:
            raise HTTPException(status_code=409 , detail=f"cannot decline : conversation already - '{converstaion.status}.'")
        return self.repo.set_conversation_status(conv_id, ConvStatus.BLOCKED, user_id)


#This is the one that fires when User A clicks "+ New" and sends a first message. It creates the DM if it doesn't exist yet, then saves the first message.
class OpenChatUseCase:
    def __init__(self,repo):
        self.repo=repo
    
    def execute(self,sender_id:UUID,participant_id:UUID,first_message:str):
        if sender_id==participant_id:
            raise HTTPException(status_code=400,detail="Cannot chat with youself ")
        conversation,created=self.repo.get_or_create_dm(sender_id,participant_id)
        # this dm_tuple returns (conversation,created)
        if conversation.status==ConvStatus.BLOCKED:
            raise HTTPException(status_code=403,detail="This convo is blocked ")
        saved_message=self.repo.save_message(context_type="dm", context_id=conversation.id, sender_id=sender_id, body=first_message, message_type="text")
        return (conversation,saved_message,created)
        

#SENDING A DM
# DM send rules: get_conv_send_info — for validating before sending



# BLOCKED → nobody can send → 403
# REQUESTED → only the initiator can send → if sender is NOT the initiator → 403
# ACTIVE → both can send freely
    
class SendMessageUseCase:
    
    def __init__(self,repo):
        self.repo=repo
    
    def execute(self, sender_id: UUID, conv_id: UUID, body: Optional[str] = None, message_type: str = "text", media_urls: Optional[list[str]] = None, media_metadata: Optional[dict] = None, location_lat: Optional[float] = None, location_lon: Optional[float] = None, reply_to_id: Optional[UUID] = None, deal_id: Optional[UUID] = None, personal_deal_id: Optional[UUID] = None, post_id: Optional[int] = None):

       gaurd=self.repo.get_conv_send_info(conv_id,sender_id)
       if not gaurd:
           raise HTTPException(status_code=404,detail="This conversaiton does not exist ")
       if gaurd.status == ConvStatus.BLOCKED:
           raise HTTPException(status_code=403,detail="Blocked conversation ")
       if gaurd.status == ConvStatus.REQUESTED:
            if gaurd.initiator_id is None or sender_id != gaurd.initiator_id:
                raise HTTPException(status_code=403, detail="Waiting for the other person to accept.")

       return self.repo.save_message(
            context_type="dm",
            context_id=conv_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            media_urls=media_urls,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            deal_id=deal_id,
            personal_deal_id=personal_deal_id,
            post_id=post_id,
        )


class SendGroupMessageUseCase:
    """
    Group chat send rules:
      - Sender must be a group member
      - Sender must not be frozen
      - If chat_perm == 'admins_only', sender must be admin
    """
    def __init__(self,repo):
        self.repo=repo

    def execute(self, sender_id: UUID, group_id: UUID, body: Optional[str] = None, message_type: str = "text", media_urls: Optional[list[str]] = None, media_metadata: Optional[dict] = None, location_lat: Optional[float] = None, location_lon: Optional[float] = None, reply_to_id: Optional[UUID] = None, deal_id: Optional[UUID] = None, post_id: Optional[int] = None):
        chat_perm = self.repo.get_group_chat_perm(group_id)
        if chat_perm is None:
            raise HTTPException(status_code=404, detail="Group not found.")

        member_role = self.repo.get_group_member_role(group_id, sender_id)
        if member_role is None:
            raise HTTPException(status_code=403, detail="Not a member of this group.")

        if self.repo.is_group_member_frozen(group_id, sender_id):
            raise HTTPException(status_code=403, detail="You are frozen in this group and cannot send messages.")

        if chat_perm == "admins_only" and member_role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can send messages in this group.")

        return self.repo.save_message(
            context_type="group",
            context_id=group_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            media_urls=media_urls,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            deal_id=deal_id,
            post_id=post_id,
        )
        # personal_deal_id is not passed here — group messages can only reference group_deals



class GetGroupMessagesUseCase:
    def __init__(self,repo):
        self.repo=repo

    def execute(self,user_id:UUID,group_id:UUID,before:Optional[datetime]=None,limit:int=50):
        member_role=self.repo.get_group_member_role(group_id,user_id)
        if member_role is None:
            raise HTTPException(status_code=403,detail="Not a member of this group.")
        return self.repo.get_messages("group",group_id,before,min(limit,100))


class CreatePersonalDealUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, sender_id: UUID, conv_id: UUID, **deal_fields):
        conv = self.repo.get_conversation(conv_id, sender_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        if conv.status != ConvStatus.ACTIVE:
            raise HTTPException(status_code=403, detail="Can only create deals in an active conversation.")
        return self.repo.create_personal_deal(conv_id=conv_id, sender_id=sender_id, **deal_fields)


class DeleteMessageUseCase:
    """Soft-delete a message. Only the sender may delete their own message."""
    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, message_id: UUID):
        info = self.repo.soft_delete_message(message_id, user_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Message not found or you cannot delete it.")
        return info
