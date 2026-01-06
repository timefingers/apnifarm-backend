from fastapi import Depends, HTTPException, status, Header
from firebase_admin import auth, credentials, initialize_app
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
import os
from dotenv import load_dotenv
from .database import get_db
from .models import User

load_dotenv()

# Initialize Firebase Admin
cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-credentials.json")
try:
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        initialize_app(cred)
    else:
        initialize_app()
except Exception:
    # Already initialized
    pass

async def verify_firebase_token(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    
    try:
        # Expect "Bearer <token>"
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
             raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
            )
        
        token = parts[1]
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
        )

async def get_current_user(
    token_data: dict = Depends(verify_firebase_token),
    db: AsyncSession = Depends(get_db)
) -> User:
    firebase_uid = token_data["uid"]
    stmt = select(User).filter(User.firebase_uid == firebase_uid)
    result = await db.execute(stmt)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in system. Please register first via POST /users/",
        )
    return user
