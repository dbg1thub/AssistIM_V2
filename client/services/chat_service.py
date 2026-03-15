"""
Chat Service Module

Service for chat operations via HTTP API.
"""
from typing import Optional

from client.core import logging
from client.core.logging import setup_logging
from client.models.message import ChatMessage, MessageStatus, MessageType
from client.network.http_client import get_http_client
from client.storage.database import get_database


setup_logging()
logger = logging.get_logger(__name__)

class ChatService:
    """
    Service for managing chat messages via HTTP API.
    
    Responsibilities:
        - Send messages to server
        - Fetch chat history
        - Local message caching
    """
    
    def __init__(self):
        self._http = get_http_client()
        self._db = get_database()
    
    async def send_message(
        self,
        session_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        sender_id: str = "",
        msg_id: Optional[str] = None,
    ) -> ChatMessage:
        """
        Send a message via HTTP API.
        
        Args:
            session_id: Target session ID
            content: Message content
            message_type: Type of message
            sender_id: Sender user ID
            msg_id: Optional message ID (generated if not provided)
        
        Returns:
            Sent ChatMessage with updated status
        """
        import uuid
        from datetime import datetime
        
        if not msg_id:
            msg_id = str(uuid.uuid4())
        
        message = ChatMessage(
            message_id=msg_id,
            session_id=session_id,
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            status=MessageStatus.SENDING,
            timestamp=datetime.now(),
            is_self=True,
        )
        
        await self._db.save_message(message)
        
        try:
            data = await self._http.post(
                "/api/chat/send",
                json={
                    "session_id": session_id,
                    "content": content,
                    "message_type": message_type.value,
                    "msg_id": msg_id,
                },
            )
            
            if data:
                message.status = MessageStatus.SENT
                logger.info(f"Message sent: {msg_id}")
            else:
                message.status = MessageStatus.FAILED
                logger.warning(f"Message send returned no data: {msg_id}")
        
        except Exception as e:
            message.status = MessageStatus.FAILED
            logger.error(f"Failed to send message: {e}")
        
        await self._db.save_message(message)
        return message
    
    async def get_history(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """
        Get chat history for a session.
        
        First checks local cache, then fetches from server if needed.
        
        Args:
            session_id: Session ID
            limit: Maximum number of messages
            before_timestamp: Load messages before this timestamp
        
        Returns:
            List of chat messages
        """
        local_messages = await self._db.get_messages(
            session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )
        
        if local_messages:
            logger.debug(f"Using cached messages for session {session_id}: {len(local_messages)}")
            return local_messages
        
        try:
            params = {
                "session_id": session_id,
                "limit": limit,
            }
            if before_timestamp:
                params["before"] = before_timestamp
            
            data = await self._http.get("/api/chat/history", params=params)
            
            messages = []
            if data and "messages" in data:
                for msg_data in data["messages"]:
                    message = ChatMessage.from_dict(msg_data)
                    messages.append(message)
                    await self._db.save_message(message)
            
            logger.info(f"Fetched {len(messages)} messages for session {session_id}")
            return messages
        
        except Exception as e:
            logger.error(f"Failed to fetch history: {e}")
            return []
    
    async def sync_messages(self, session_id: str, last_seq: int) -> list[ChatMessage]:
        """
        Sync messages after reconnection.
        
        Args:
            session_id: Session ID
            last_seq: Last received message sequence number
        
        Returns:
            List of missed messages
        """
        try:
            data = await self._http.post(
                "/api/chat/sync",
                json={
                    "session_id": session_id,
                    "last_seq": last_seq,
                },
            )
            
            if not data or "messages" not in data:
                return []
            
            messages = []
            for msg_data in data["messages"]:
                message = ChatMessage.from_dict(msg_data)
                messages.append(message)
                await self._db.save_message(message)
            
            logger.info(f"Synced {len(messages)} messages for session {session_id}")
            return messages
        
        except Exception as e:
            logger.error(f"Failed to sync messages: {e}")
            return []
    
    async def delete_message(self, message_id: str) -> bool:
        """
        Delete a message.
        
        Args:
            message_id: Message ID to delete
        
        Returns:
            True if successful
        """
        try:
            await self._http.delete(f"/api/chat/message/{message_id}")
            await self._db.delete_message(message_id)
            logger.info(f"Message deleted: {message_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")
            return False
    
    async def mark_as_read(self, session_id: str, message_id: str) -> bool:
        """
        Mark message as read.
        
        Args:
            session_id: Session ID
            message_id: Last read message ID
        
        Returns:
            True if successful
        """
        try:
            await self._http.post(
                "/api/chat/read",
                json={
                    "session_id": session_id,
                    "message_id": message_id,
                },
            )
            
            await self._db.update_session_unread(session_id, 0)
            logger.info(f"Marked messages as read in session {session_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to mark as read: {e}")
            return False


_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get the global chat service instance."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
