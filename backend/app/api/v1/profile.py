"""
Candidate profile — read and update.

Resume parsing fills this in, but every field can be corrected by hand. Manual
edits are never silently overwritten by a new upload (the parser only fills
missing scalars and merges skills).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.core import CandidateProfile, User
from app.schemas.profile import ProfileOut, ProfileUpdate

router = APIRouter()


async def _get_or_404(db: AsyncSession, user_id) -> CandidateProfile:
    result = await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    return profile


@router.get("", response_model=ProfileOut)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_or_404(db, current_user.id)


@router.put("", response_model=ProfileOut)
@router.patch("", response_model=ProfileOut)
async def update_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_404(db, current_user.id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(profile, field, value)
    if profile.email is None:
        profile.email = current_user.email
    await db.commit()
    await db.refresh(profile)
    return profile
