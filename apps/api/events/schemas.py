"""Event payload schemas for internal API events."""

import msgspec


class OcrVerificationRequestedEvent(msgspec.Struct):
    """Event emitted when OCR auto-verification should be attempted."""

    completion_id: int
    user_id: int
    code: str
    time: float
    screenshot: str
