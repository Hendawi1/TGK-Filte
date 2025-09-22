from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.errors import ChannelPrivateError
import logging

async def verify_channel_admin(user_id, target_channel, client):
    try:
        channel_entity = await client.get_entity(target_channel)
        
        participants = await client(GetParticipantsRequest(
            channel=channel_entity,
            filter=ChannelParticipantsAdmins(),
            offset=0,
            limit=100,
            hash=0
        ))
        
        for user in participants.users:
            if user.id == user_id:
                return True
        return False
        
    except ChannelPrivateError:
        return False
    except Exception as e:
        logging.error(f"Ошибка проверки прав: {str(e)}")
        return False
