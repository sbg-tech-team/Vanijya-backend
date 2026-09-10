from typing import Any


def ok(data: Any = None, message: str = "Success") -> dict:
    return {"success": True, "message": message, "data": data}
