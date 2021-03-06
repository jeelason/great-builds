from postgres.db import UsersQueries
from fastapi import (
    Depends,
    HTTPException,
    status,
    Response,
    Cookie,
    APIRouter,
    Request,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt, jws, JWSError
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional
import os

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
COOKIE_NAME = "jwtdown_access_token"


router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


class HttpError(BaseModel):
    detail: str


class TokenData(BaseModel):
    username: str


class AccessToken(BaseModel):
    token: str


class User(BaseModel):
    id: int
    user: str
    password: str
    email: str


class UserSignUp(BaseModel):
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None
    password: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def row_to_user(row):
    user = {
        "id": row[0],
        "user": row[1],
        "password": row[2],
        "email": row[3],
    }
    return user


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(repo: UsersQueries, username: str, password: str):
    user = repo.get_user(username)
    if not user:
        return False
    if not verify_password(password, user[2]):
        return False
    return user


def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    cookie_token: Optional[str] | None = (
        Cookie(default=None, alias=COOKIE_NAME)
        ),
    repo: UsersQueries = Depends(),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = bearer_token
    if not token and cookie_token:
        token = cookie_token
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except (JWTError, AttributeError):
        raise credentials_exception
    user = repo.get_user(username)
    if user is None:
        raise credentials_exception
    return row_to_user(user)


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
):
    # if current_user.disabled:
    #     raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@router.post("/token")
async def login_for_access_token(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    repo: UsersQueries = Depends(),
):
    user = authenticate_user(repo, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user[1]},
    )
    token = {"access_token": access_token, "token_type": "bearer"}
    headers = request.headers
    samesite = "none"
    secure = True
    if "origin" in headers and "localhost" in headers["origin"]:
        samesite = "lax"
        secure = False
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite=samesite,
        secure=secure,
    )
    return token


@router.get("/token", response_model=AccessToken)
async def get_token(request: Request):
    if COOKIE_NAME in request.cookies:
        return {"token": request.cookies[COOKIE_NAME]}


@router.post("/api/users")
async def signup(user: UserSignUp, repo: UsersQueries = Depends()):
    hashed_password = pwd_context.hash(user.password)
    repo.create_user(user.username, hashed_password, user.email)


@router.get(
    "/users/me",
    response_model=User,
    responses={
        200: {"model": User},
        400: {"model": HttpError},
        401: {"model": HttpError},
    },
)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user


@router.post("/token/validate")
async def validate_token(access_token: AccessToken, response: Response):
    try:
        return jws.verify(access_token.token, SECRET_KEY, algorithms=ALGORITHM)
    except JWSError:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": "Not a good token"}


@router.delete("/token")
async def logout(request: Request, response: Response):
    samesite = "none"
    headers = request.headers
    secure = True
    if "origin" in headers and "localhost" in headers["origin"]:
        samesite = "lax"
        secure = False
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite=samesite,
        secure=secure,
    )
