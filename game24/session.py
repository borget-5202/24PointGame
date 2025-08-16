# session.py
import uuid
from fastapi import Request, Response

SESSION_COOKIE_NAME = "session_id"

def get_or_create_session_id(request: Request, response: Response) -> str:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        sid = str(uuid.uuid4())
        print( f"get session id = uuid.uuid4")
        response.set_cookie(key=SESSION_COOKIE_NAME, value=sid, httponly=True)
    print( f"get session id = {sid}")
    return sid

