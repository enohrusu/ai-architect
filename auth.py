from passlib.context import CryptContext
from database import get_connection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    password = password[:72]  # 🔥 fix bcrypt limit
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_password = plain_password[:72]  # 🔥 same fix here
    return pwd_context.verify(plain_password, hashed_password)


def create_user(email: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()

    hashed = hash_password(password)

    try:
        cursor.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            (email, hashed)
        )
        conn.commit()
        return True, "User created successfully"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def authenticate_user(email: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return None

    if not verify_password(password, user["password"]):
        return None

    return {
        "id": user["id"],
        "email": user["email"],
        "is_pro": bool(user["is_pro"])
    }