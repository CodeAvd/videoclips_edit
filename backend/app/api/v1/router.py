from fastapi import APIRouter

from app.api.v1.endpoints import brand_profiles, candidate_clips, health, jobs, platform_accounts, source_videos, transcripts, uploads

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(brand_profiles.router, prefix="/brand-profiles", tags=["brand-profiles"])
api_router.include_router(platform_accounts.router, prefix="/platform-accounts", tags=["platform-accounts"])
api_router.include_router(source_videos.router, prefix="/source-videos", tags=["source-videos"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(transcripts.router, tags=["transcripts"])
api_router.include_router(candidate_clips.router, tags=["candidate-clips"])
