"""
Auth routes.

Kept deliberately thin: parse request -> call service -> shape response.
No business logic here — that all lives in UserService / AuthService.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.v1.dependencies.auth import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.auth import Token
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import AuthService, InvalidCredentialsError
from app.services.user_service import EmailAlreadyRegisteredError, UserService
from app.api.v1.dependencies.rbac import require_role


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    """Register a new user account."""
    try:
        return UserService(db).register_user(payload)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """
    Log in and receive a JWT access token.

    Uses OAuth2PasswordRequestForm (form-encoded username/password) rather
    than a JSON body — this is the OAuth2 "password" flow shape that
    Swagger UI's Authorize button expects, so /docs can log you in directly.
    Note: 'username' is the form field name; we treat it as the email.
    """
    try:
        access_token = AuthService(db).login(email=form_data.username, password=form_data.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user. Proves the whole auth chain works end to end."""
    return current_user

@router.get("/admin-only-test", response_model=UserRead)
def admin_only_test(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> User:
    """
    TEMPORARY test route proving RBAC works. Delete this once real admin-only
    endpoints (e.g. job posting management) exist in Milestone 3.
    """
    return current_user    
