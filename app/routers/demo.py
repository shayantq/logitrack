"""
ورود به نسخه نمایشی خصوصی با لینک مخفی — در مستندات API دیده نمی‌شود و بدون توکن درست، مثل مسیری ناموجود 404 می‌دهد.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel, Field

from app.core import demo
from app.core.security import ALGORITHM, SECRET_KEY
from app.models import User

router = APIRouter(prefix="/demo", include_in_schema=False)


class DemoSessionIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router.post("/session")
def start_session(data: DemoSessionIn):
    if not demo.token_matches(data.token):
        raise HTTPException(status_code=404, detail="Not Found")
    db = demo.session_factory()()
    try:
        user = db.query(User).filter(User.username == demo.DEMO_USERNAME).first()
        if user is None:
            raise HTTPException(status_code=503, detail="نسخه نمایشی در حال آماده‌سازی است؛ چند دقیقه دیگر دوباره امتحان کنید.")
        token = jwt.encode({"sub": user.username, "id": user.id, "tv": user.token_version or 0, "demo": True,
                            "exp": datetime.now(timezone.utc) + timedelta(hours=demo.SESSION_HOURS)}, SECRET_KEY, algorithm=ALGORITHM)
        return {"access_token": token, "token_type": "bearer", "reset_minutes": demo.RESET_MINUTES}
    finally:
        db.close()
