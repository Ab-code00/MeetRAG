from enum import StrEnum


class UserRole(StrEnum):
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"
    OWNER = "OWNER"


class MeetingStatus(StrEnum):
    PENDING = "PENDING"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBED = "TRANSCRIBED"
    CLEANING = "CLEANING"
    CLEANED = "CLEANED"
    CHUNKING = "CHUNKING"
    CHUNKED = "CHUNKED"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    DELETED = "DELETED"


class JobStage(StrEnum):
    TRANSCRIBE = "TRANSCRIBE"
    CLEAN = "CLEAN"
    CHUNK = "CHUNK"
    EMBED_INDEX = "EMBED_INDEX"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class RecordingStatus(StrEnum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class ChatRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ChunkType(StrEnum):
    TURN = "TURN"
    CONTEXT = "CONTEXT"

