import base64, os, hashlib, hmac, json, time
from typing import Optional, Tuple

def pbkdf2_hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if salt is None:
        salt = base64.urlsafe_b64encode(os.urandom(18)).decode("utf-8").rstrip("=")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return salt, base64.urlsafe_b64encode(dk).decode("utf-8").rstrip("=")

def verify_password(password: str, salt: str, hashed: str) -> bool:
    _, hashed2 = pbkdf2_hash_password(password, salt=salt)
    return hmac.compare_digest(hashed2, hashed)

def sign(payload: str, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")

def make_session_token(user_id: int, email: str, secret: str, ttl_seconds: int = 60*60*24*7) -> str:
    exp = int(time.time()) + int(ttl_seconds)
    data = {"uid": int(user_id), "email": str(email), "exp": exp}
    payload = base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{payload}.{sign(payload, secret)}"

def parse_session_token(token: str, secret: str):
    try:
        payload, sig = token.split(".", 1)
        if sign(payload, secret) != sig:
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "===").decode("utf-8"))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except Exception:
        return None
