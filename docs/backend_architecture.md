# AssistIM Backend Architecture

Version: 1.0
Architecture Style: RESTful + WebSocket
Backend Framework: FastAPI

---

# 1. Project Overview

AssistIM 是一个 **AI增强即时通讯系统**。

系统包含：

* Desktop Client
* Backend API
* WebSocket Real-time Server
* File Storage
* AI Assistant

核心功能：

* 用户系统
* 好友系统
* 聊天系统
* 群聊系统
* 朋友圈系统
* 文件系统
* AI聊天
* 实时消息

---

# 2. Technology Stack

Backend Framework

FastAPI

ASGI Server

Uvicorn

ORM

SQLAlchemy 2.0

Database

PostgreSQL

Cache

Redis

Schema Validation

Pydantic

Authentication

JWT

Password Hashing

bcrypt

Migration

Alembic

---

# 3. Backend Architecture Pattern

系统使用 **四层架构**

API Layer
Service Layer
Repository Layer
Database Layer

结构如下

```
Client
 ↓
API Router
 ↓
Service
 ↓
Repository
 ↓
Database
```

---

# 4. Backend Directory Structure

```
server

app
 ├── main.py
 ├── core
 ├── api
 ├── models
 ├── schemas
 ├── services
 ├── repositories
 ├── websocket
 ├── dependencies
 └── utils

alembic
tests
docs
```

---

# 5. Detailed Directory Structure

```
app

core
api
models
schemas
services
repositories
websocket
dependencies
utils
```

---

# 6. Core Directory

```
app/core
```

Files

```
config.py
database.py
security.py
logging.py
```

Responsibilities

Configuration management
Database initialization
Security configuration
Logging setup

---

# 7. API Layer

```
app/api/v1
```

Structure

```
auth.py
users.py
friends.py
sessions.py
messages.py
groups.py
moments.py
files.py
```

Responsibilities

HTTP request handling
Request validation
Response formatting

---

# 8. Models Layer

```
app/models
```

SQLAlchemy models。

Example

```
user.py
message.py
group.py
friend.py
session.py
moment.py
```

---

# 9. Schemas Layer

```
app/schemas
```

Pydantic models。

Example

```
user_schema.py
auth_schema.py
message_schema.py
```

---

# 10. Services Layer

```
app/services
```

Business logic layer。

Example

```
auth_service.py
message_service.py
friend_service.py
group_service.py
moment_service.py
```

Responsibilities

Authentication logic
Chat logic
Friend management

---

# 11. Repository Layer

```
app/repositories
```

Database operations。

Example

```
user_repo.py
message_repo.py
friend_repo.py
```

Responsibilities

CRUD operations
Query abstraction

---

# 12. WebSocket Layer

```
app/websocket
```

Files

```
manager.py
chat_ws.py
presence_ws.py
```

Responsibilities

Real-time message delivery
User presence
Typing indicator

---

# 13. Dependencies

```
app/dependencies
```

Example

```
auth_dependency.py
```

Responsibilities

JWT validation
User authentication

---

# 14. Utils

```
app/utils
```

Utilities

```
jwt.py
password.py
response.py
time.py
```

---

# 15. Configuration System

Environment configuration stored in `.env`.

Example

```
DATABASE_URL
SECRET_KEY
ACCESS_TOKEN_EXPIRE
REDIS_URL
```

---

# 16. Example main.py

```python
from fastapi import FastAPI
from app.api.v1.router import api_router

app = FastAPI(
    title="AssistIM API",
    version="1.0"
)

app.include_router(api_router, prefix="/api/v1")
```

---

# 17. API Router

```
app/api/v1/router.py
```

Example

```python
from fastapi import APIRouter

from .auth import router as auth_router
from .users import router as users_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(users_router, prefix="/users")
```

---

# 18. RESTful API Rules

Rules

1 Resource based URL
2 Use HTTP methods
3 Stateless design

Example

```
GET /users
POST /users
GET /users/{id}
DELETE /users/{id}
```

---

# 19. API Response Format

Success

```
{
 "code":0,
 "message":"success",
 "data":{}
}
```

Error

```
{
 "code":4001,
 "message":"invalid request"
}
```

---

# 20. Authentication System

Authentication uses **JWT**.

Flow

```
Login
 ↓
Generate Token
 ↓
Client stores token
 ↓
Client sends Authorization header
```

Header

```
Authorization: Bearer <token>
```

---

# 21. Password Hashing

Passwords stored as bcrypt hashes.

Process

```
password → bcrypt → hash
```

---

# 22. Token Structure

Example JWT payload

```
{
 "sub":1,
 "username":"user1",
 "exp":1760000000
}
```

---

# 23. Rate Limiting

System should implement request rate limiting.

Example

```
login: 5 requests/min
register: 3 requests/min
```

---

# 24. Logging System

Use structured logging.

Log types

```
access log
error log
security log
```

---

# 25. Error Codes

Example

```
1001 invalid credentials
1002 user exists
1003 user not found
1004 unauthorized
```

---

# 26. Future Modules

Planned modules

User system
Friend system
Chat system
Group chat
Moments
File storage
AI assistant

Next chapters will define them in detail.

# 27. Database Architecture

Database: PostgreSQL

Design principles

1 Normalized structure
2 Clear relations
3 Indexed queries
4 Optimized for chat workloads

---

# 28. Database Tables Overview

Main tables

users
friend_requests
friends
sessions
messages
groups
group_members
moments
moment_likes
moment_comments
files

---

# 29. Users Table

Table name

users

Fields

id
username
password_hash
nickname
avatar
status
created_at

Schema

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(32) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname VARCHAR(64) NOT NULL,
    avatar TEXT,
    status VARCHAR(16) DEFAULT 'offline',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Indexes

```sql
CREATE INDEX idx_users_username ON users(username);
```

---

# 30. Friend Requests Table

Table

friend_requests

Fields

id
sender_id
receiver_id
status
created_at

Schema

```sql
CREATE TABLE friend_requests (
    id BIGSERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL,
    receiver_id BIGINT NOT NULL,
    status VARCHAR(16) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Status

pending
accepted
rejected

---

# 31. Friends Table

Table

friends

Fields

id
user_id
friend_id
created_at

Schema

```sql
CREATE TABLE friends (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    friend_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Indexes

```sql
CREATE INDEX idx_friends_user_id ON friends(user_id);
```

---

# 32. Sessions Table

Session represents a chat conversation.

Table

sessions

Fields

id
type
created_at

Types

private
group

Schema

```sql
CREATE TABLE sessions (
    id BIGSERIAL PRIMARY KEY,
    type VARCHAR(16) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 33. Session Members Table

Table

session_members

Fields

session_id
user_id
joined_at

Schema

```sql
CREATE TABLE session_members (
    session_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(session_id,user_id)
);
```

---

# 34. Messages Table

Table

messages

Fields

id
session_id
sender_id
type
content
created_at

Message types

text
image
file
system

Schema

```sql
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL,
    sender_id BIGINT NOT NULL,
    type VARCHAR(16) NOT NULL,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Indexes

```sql
CREATE INDEX idx_messages_session_id ON messages(session_id);
```

---

# 35. Message Read Status

Table

message_reads

Fields

message_id
user_id
read_at

Schema

```sql
CREATE TABLE message_reads (
    message_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(message_id,user_id)
);
```

---

# 36. Groups Table

Table

groups

Fields

id
name
owner_id
created_at

Schema

```sql
CREATE TABLE groups (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    owner_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 37. Group Members

Table

group_members

Fields

group_id
user_id
role

Roles

owner
admin
member

Schema

```sql
CREATE TABLE group_members (
    group_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role VARCHAR(16) DEFAULT 'member',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(group_id,user_id)
);
```

---

# 38. Moments Table

朋友圈动态

Table

moments

Fields

id
user_id
content
created_at

Schema

```sql
CREATE TABLE moments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 39. Moment Likes

Table

moment_likes

Fields

moment_id
user_id
created_at

Schema

```sql
CREATE TABLE moment_likes (
    moment_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(moment_id,user_id)
);
```

---

# 40. Moment Comments

Table

moment_comments

Fields

id
moment_id
user_id
content
created_at

Schema

```sql
CREATE TABLE moment_comments (
    id BIGSERIAL PRIMARY KEY,
    moment_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 41. Files Table

Table

files

Fields

id
user_id
file_url
file_type
created_at

Schema

```sql
CREATE TABLE files (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    file_url TEXT NOT NULL,
    file_type VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 42. Database Relations

Relations

users → friends
users → messages
sessions → messages
groups → group_members

Example

User

↓

Sessions

↓

Messages

---

# 43. Message Flow

Message send process

Client sends message

↓

API receives request

↓

Message stored in database

↓

WebSocket broadcast

---

# 44. Index Strategy

Indexes required

users.username
messages.session_id
friends.user_id
group_members.group_id

---

# 45. Scaling Considerations

Future scaling

Partition messages table
Use Redis cache
Use message queue

---

# 46. Database Migration

Migration tool

Alembic

Example

```bash
alembic revision --autogenerate
alembic upgrade head
```

---

# 47. Future Database Extensions

Possible additions

message_reactions
message_attachments
user_settings
notification_queue

# 48. RESTful API Design

All APIs follow RESTful principles.

Rules

1 Resource-based URLs
2 Use HTTP verbs
3 Stateless requests
4 JSON responses

Base URL

/api/v1

---

# 49. Authentication APIs

Authentication endpoints.

Endpoints

POST /auth/login
POST /auth/users
POST /auth/token
DELETE /auth/session
GET /auth/me

---

# 50. User Registration

Endpoint

POST /auth/users

Request

```json id="req01"
{
 "username": "string",
 "password": "string",
 "nickname": "string"
}
```

Response

```json id="res01"
{
 "id":1,
 "username":"user1",
 "nickname":"User One",
 "created_at":"2026-03-16T12:00:00Z"
}
```

HTTP Status

201 Created

---

# 51. User Login

Endpoint

POST /auth/login

Request

```json id="req02"
{
 "username":"string",
 "password":"string"
}
```

Response

```json id="res02"
{
 "access_token":"jwt_token",
 "refresh_token":"refresh_token",
 "token_type":"Bearer",
 "expires_in":7200
}
```

HTTP Status

200 OK

---

# 52. Refresh Token

Endpoint

POST /auth/token

Request

```json id="req03"
{
 "refresh_token":"string"
}
```

Response

```json id="res03"
{
 "access_token":"new_token",
 "token_type":"Bearer",
 "expires_in":7200
}
```

---

# 53. Logout

Endpoint

DELETE /auth/session

Headers

Authorization: Bearer token

Response

204 No Content

---

# 54. Current User

Endpoint

GET /auth/me

Response

```json id="res04"
{
 "id":1,
 "username":"user1",
 "nickname":"User One",
 "avatar":"url",
 "created_at":"2026-03-16T12:00:00Z"
}
```

---

# 55. Users API

User resources.

Endpoints

GET /users/{id}
GET /users/search

---

# 56. Get User Profile

Endpoint

GET /users/{id}

Response

```json id="res05"
{
 "id":1,
 "username":"user1",
 "nickname":"User One",
 "avatar":"url"
}
```

---

# 57. Search Users

Endpoint

GET /users/search

Query Parameters

keyword

Example

/users/search?keyword=test

Response

```json id="res06"
[
 {
  "id":2,
  "username":"testuser",
  "nickname":"Test"
 }
]
```

---

# 58. Friend System Overview

Friend system includes

friend requests
friend list
accept/reject requests

Tables used

friend_requests
friends

---

# 59. Send Friend Request

Endpoint

POST /friends/requests

Request

```json id="req04"
{
 "user_id":2,
 "message":"hello"
}
```

Response

```json id="res07"
{
 "id":10,
 "status":"pending"
}
```

---

# 60. List Friend Requests

Endpoint

GET /friends/requests

Response

```json id="res08"
[
 {
  "id":10,
  "sender_id":2,
  "status":"pending"
 }
]
```

---

# 61. Accept Friend Request

Endpoint

POST /friends/requests/{id}/accept

Response

```json id="res09"
{
 "status":"accepted"
}
```

---

# 62. Reject Friend Request

Endpoint

POST /friends/requests/{id}/reject

Response

```json id="res10"
{
 "status":"rejected"
}
```

---

# 63. Friend List

Endpoint

GET /friends

Response

```json id="res11"
[
 {
  "id":2,
  "username":"friend1",
  "nickname":"Friend One",
  "avatar":"url"
 }
]
```

---

# 64. Delete Friend

Endpoint

DELETE /friends/{id}

Response

204 No Content

---

# 65. Friend Relationship Check

Endpoint

GET /friends/check/{user_id}

Response

```json id="res12"
{
 "is_friend":true
}
```

---

# 66. Pagination Rules

List endpoints support pagination.

Parameters

page
size

Example

/users/search?page=1&size=20

Response

```json id="res13"
{
 "total":100,
 "page":1,
 "size":20,
 "items":[]
}
```

---

# 67. Error Handling

Standard error response

```json id="err01"
{
 "code":4001,
 "message":"invalid request"
}
```

Common errors

400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found
500 Server Error

---

# 68. API Versioning

All APIs include version prefix.

Example

/api/v1/users

Future

/api/v2

---

# 69. Authentication Middleware

All protected endpoints require token.

Header

Authorization: Bearer token

Validation process

Verify JWT
Extract user_id
Load user

---

# 70. Rate Limiting

Endpoints should apply limits.

Examples

login → 5/min
register → 3/min
friend request → 10/min

---

# 71. Logging

Log API requests.

Example fields

timestamp
user_id
endpoint
status_code

# 72. Chat System Overview

The chat system is the core of AssistIM.

Main components

sessions
session_members
messages
message_reads

Features

private chat
group chat
message history
read receipts
message recall

---

# 73. Session Resource

Session represents a conversation.

Types

private
group

Endpoints

GET /sessions
POST /sessions
GET /sessions/{id}
DELETE /sessions/{id}

---

# 74. Create Private Session

Endpoint

POST /sessions

Request

```json id="req10"
{
 "type":"private",
 "user_id":2
}
```

Response

```json id="res20"
{
 "id":100,
 "type":"private",
 "created_at":"2026-03-16T12:00:00Z"
}
```

---

# 75. List Sessions

Endpoint

GET /sessions

Response

```json id="res21"
[
 {
  "id":100,
  "type":"private",
  "last_message":"hello",
  "updated_at":"2026-03-16T12:10:00Z"
 }
]
```

---

# 76. Get Session

Endpoint

GET /sessions/{id}

Response

```json id="res22"
{
 "id":100,
 "type":"private",
 "members":[
  {
   "id":1,
   "nickname":"User1"
  },
  {
   "id":2,
   "nickname":"User2"
  }
 ]
}
```

---

# 77. Delete Session

Endpoint

DELETE /sessions/{id}

Response

204 No Content

---

# 78. Message Resource

Message represents a chat message.

Fields

id
session_id
sender_id
type
content
created_at

Types

text
image
file
system

---

# 79. Send Message

Endpoint

POST /messages

Request

```json id="req11"
{
 "session_id":100,
 "type":"text",
 "content":"hello"
}
```

Response

```json id="res23"
{
 "id":500,
 "session_id":100,
 "sender_id":1,
 "type":"text",
 "content":"hello",
 "created_at":"2026-03-16T12:00:00Z"
}
```

---

# 80. Message History

Endpoint

GET /messages/history

Query Parameters

session_id
before_id
limit

Example

/messages/history?session_id=100&limit=20

Response

```json id="res24"
[
 {
  "id":500,
  "content":"hello",
  "sender_id":1
 }
]
```

---

# 81. Load Older Messages

Pagination uses message id.

Example

/messages/history?session_id=100&before_id=500

Response returns older messages.

---

# 82. Message Read Receipt

Endpoint

POST /messages/read

Request

```json id="req12"
{
 "message_id":500
}
```

Response

```json id="res25"
{
 "status":"read"
}
```

---

# 83. Batch Read

Endpoint

POST /messages/read/batch

Request

```json id="req13"
{
 "session_id":100,
 "last_read_id":500
}
```

Response

```json id="res26"
{
 "success":true
}
```

---

# 84. Message Recall

Endpoint

POST /messages/{id}/recall

Rules

Only sender can recall message.

Time limit example

2 minutes.

Response

```json id="res27"
{
 "status":"recalled"
}
```

---

# 85. Message Delete

Endpoint

DELETE /messages/{id}

Response

204 No Content

---

# 86. Message Types

Supported types

text
image
file
system

Example

```json id="msg01"
{
 "type":"text",
 "content":"hello"
}
```

---

# 87. Image Message

Example

```json id="msg02"
{
 "type":"image",
 "content":"https://cdn.server/image.jpg"
}
```

---

# 88. File Message

Example

```json id="msg03"
{
 "type":"file",
 "content":"https://cdn.server/file.pdf"
}
```

---

# 89. Typing Indicator

Endpoint

POST /sessions/{id}/typing

Request

```json id="req14"
{
 "typing":true
}
```

Used for real-time typing notifications.

---

# 90. Unread Messages

Endpoint

GET /messages/unread

Response

```json id="res28"
{
 "total":15
}
```

---

# 91. Session Unread Count

Endpoint

GET /sessions/unread

Response

```json id="res29"
[
 {
  "session_id":100,
  "unread":3
 }
]
```

---

# 92. Message Ordering

Messages ordered by

id ASC

Example

1
2
3
4

---

# 93. Message ID Strategy

Use auto increment id.

Advantages

ordered
easy pagination
fast query

---

# 94. Message Storage

Messages stored in database.

Flow

Client → API → DB → WebSocket broadcast

---

# 95. Performance Optimization

For large systems

partition messages table

Example

messages_2026
messages_2027

---

# 96. Message Cache

Redis cache for

recent messages
session metadata

---

# 97. Message Queue

Future scaling

Kafka
RabbitMQ

---

# 98. Security Rules

Check session membership before sending message.

Verify

user_id ∈ session_members

# 99. Group Chat System Overview

Group chat allows multiple users to communicate in one session.

Main components

groups
group_members
messages

Roles

owner
admin
member

Features

create group
invite members
remove members
group messaging

---

# 100. Group Resource

Group represents a chat group.

Endpoints

POST /groups
GET /groups
GET /groups/{id}
DELETE /groups/{id}

---

# 101. Create Group

Endpoint

POST /groups

Request

```json id="req20"
{
 "name":"Study Group",
 "members":[2,3,4]
}
```

Response

```json id="res40"
{
 "id":200,
 "name":"Study Group",
 "owner_id":1
}
```

HTTP Status

201 Created

---

# 102. List Groups

Endpoint

GET /groups

Response

```json id="res41"
[
 {
  "id":200,
  "name":"Study Group",
  "member_count":5
 }
]
```

---

# 103. Get Group

Endpoint

GET /groups/{id}

Response

```json id="res42"
{
 "id":200,
 "name":"Study Group",
 "owner_id":1,
 "members":[
  {
   "user_id":1,
   "role":"owner"
  },
  {
   "user_id":2,
   "role":"member"
  }
 ]
}
```

---

# 104. Delete Group

Endpoint

DELETE /groups/{id}

Rules

Only owner can delete group.

Response

204 No Content

---

# 105. Add Group Member

Endpoint

POST /groups/{id}/members

Request

```json id="req21"
{
 "user_id":5
}
```

Response

```json id="res43"
{
 "status":"added"
}
```

---

# 106. Remove Group Member

Endpoint

DELETE /groups/{id}/members/{user_id}

Response

204 No Content

---

# 107. Group Member Role

Roles

owner
admin
member

Permissions

owner → full control
admin → manage members
member → send messages

---

# 108. Leave Group

Endpoint

POST /groups/{id}/leave

Response

```json id="res44"
{
 "status":"left"
}
```

---

# 109. Transfer Ownership

Endpoint

POST /groups/{id}/transfer

Request

```json id="req22"
{
 "new_owner_id":3
}
```

---

# 110. WebSocket Overview

WebSocket used for real-time communication.

Main channels

/ws/chat
/ws/presence

---

# 111. Chat WebSocket

Connection URL

/ws/chat

Authentication

Token required.

Example

ws://server/ws/chat?token=JWT

---

# 112. WebSocket Message Format

Client → Server

```json id="ws01"
{
 "type":"message",
 "session_id":100,
 "content":"hello"
}
```

Server → Client

```json id="ws02"
{
 "event":"message",
 "data":{
  "id":500,
  "session_id":100,
  "content":"hello"
 }
}
```

---

# 113. WebSocket Events

Events supported

message
typing
read
online
offline

---

# 114. Typing Event

Example

```json id="ws03"
{
 "type":"typing",
 "session_id":100
}
```

Server broadcasts typing event.

---

# 115. Read Receipt Event

Example

```json id="ws04"
{
 "type":"read",
 "message_id":500
}
```

---

# 116. Presence System

Presence tracks online users.

Events

online
offline

Example

```json id="ws05"
{
 "event":"online",
 "user_id":2
}
```

---

# 117. Connection Manager

WebSocket manager maintains active connections.

Responsibilities

store connections
broadcast messages
handle disconnects

---

# 118. Broadcast Message

Flow

message received
save to database
broadcast to session members

---

# 119. User Online State

User status stored in

Redis

States

online
offline

---

# 120. Heartbeat Mechanism

Client sends ping every 30 seconds.

Example

```json id="ws06"
{
 "type":"ping"
}
```

Server responds

```json id="ws07"
{
 "type":"pong"
}
```

---

# 121. Reconnect Strategy

Client should reconnect automatically.

Steps

disconnect
retry connection
restore sessions

---

# 122. Message Delivery Guarantee

Strategy

save to DB first
then broadcast

Ensures no message loss.

---

# 123. Scaling WebSocket

For large scale deployment

Use Redis pub/sub

Flow

Server A receives message
Publish to Redis
Server B broadcasts

---

# 124. Security

WebSocket security checks

validate token
verify session membership

---

# 125. Rate Limits

Prevent spam.

Limits

messages per second
typing events per second

---

# 126. Logging

Log WebSocket events

connect
disconnect
message send

---

# 127. Future Improvements

Possible additions

message reactions
threaded replies
voice messages
