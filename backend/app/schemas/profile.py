from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProfileOut(BaseModel):
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    experience_level: str | None = None
    total_experience_years: float | None = None
    current_title: str | None = None
    current_company: str | None = None
    expected_salary: float | None = None
    skills: list[Any] | None = None
    education: list[Any] | None = None
    experience: list[Any] | None = None
    projects: list[Any] | None = None
    certifications: list[Any] | None = None
    achievements: list[Any] | None = None
    languages: list[Any] | None = None
    preferred_roles: list[Any] | None = None
    preferred_locations: list[Any] | None = None
    preferred_work_modes: list[Any] | None = None
    extracted_data: dict[str, Any] | None = None
    completeness: int = 0

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=250)
    summary: str | None = Field(default=None, max_length=5000)
    linkedin_url: str | None = Field(default=None, max_length=500)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    experience_level: str | None = Field(default=None, max_length=40)
    total_experience_years: float | None = Field(default=None, ge=0, le=60)
    current_title: str | None = Field(default=None, max_length=200)
    current_company: str | None = Field(default=None, max_length=200)
    expected_salary: float | None = Field(default=None, ge=0)
    skills: list[str] | None = None
    education: list[dict[str, Any]] | None = None
    experience: list[dict[str, Any]] | None = None
    projects: list[dict[str, Any]] | None = None
    certifications: list[str] | None = None
    achievements: list[str] | None = None
    languages: list[str] | None = None
    preferred_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    preferred_work_modes: list[str] | None = None
