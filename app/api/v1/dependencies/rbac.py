"""
RBAC dependency.

Usage in a route:
    @router.post("/jobs")
    def create_job(current_user: User = Depends(require_role(UserRole.RECRUITER, UserRole.ADMIN))):
        ...

Role checks live here, at the route boundary — never scattered inside
service methods, where it's easy to forget one on a new endpoint.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.v1.dependencies.auth import get_current_user
from app.models.user import User, UserRole


def require_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Returns a FastAPI dependency that only permits users with one of the given roles."""

    def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _check_role