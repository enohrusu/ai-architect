from passlib.context import CryptContext
from database import get_connection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    password = password[:72]
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_password = plain_password[:72]
    return pwd_context.verify(plain_password, hashed_password)


def create_user(email: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()

    hashed = hash_password(password)

    try:
        cursor.execute(
            "INSERT INTO users (email, password) VALUES (%s, %s)",
            (email, hashed)
        )
        conn.commit()
        return True, "User created successfully"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cursor.close()
        conn.close()


def authenticate_user(email: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, email, password, is_pro, generation_count FROM users WHERE email = %s",
        (email,)
    )
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if not user:
        return None

    user_id, user_email, hashed_password, is_pro, generation_count = user

    if not verify_password(password, hashed_password):
        return None

    return {
        "id": user_id,
        "email": user_email,
        "is_pro": bool(is_pro),
        "generation_count": generation_count
    }