from datetime import timedelta

from sqlalchemy import select

from app.data.career_roles import CAREER_ROLE_SKILLS, ROLE_RESOURCE_TOPICS
from app.data.learning_resources import CURATED_RESOURCES
from app.extensions import db
from app.models import CareerRoadmap, LearningProgress, LearningResource, utc_now
from app.services.resource_verifier import ResourceVerifier


VALID_PROGRESS_STATES = frozenset({"not_started", "in_progress", "completed"})
VERIFICATION_FRESHNESS_DAYS = 30


class ResourceService:
    def __init__(self, verifier: ResourceVerifier | None = None):
        self.verifier = verifier or ResourceVerifier()

    def seed_catalog(self) -> dict[str, int]:
        verified = 0
        failed = 0
        for item in CURATED_RESOURCES:
            resource = db.session.execute(
                select(LearningResource).where(LearningResource.url == item["url"])
            ).scalar_one_or_none()
            if resource is None:
                resource = LearningResource(**item)
                db.session.add(resource)
            else:
                for field, value in item.items():
                    setattr(resource, field, value)

            if self.verifier.verify(resource.url):
                resource.verification_status = "verified"
                resource.verified_at = utc_now()
                verified += 1
            else:
                resource.verification_status = "failed"
                resource.verified_at = None
                failed += 1

        db.session.commit()
        return {"verified": verified, "failed": failed}

    def resources_for_role(self, role: str) -> list[dict]:
        topics = {topic.casefold() for topic in ROLE_RESOURCE_TOPICS[role]}
        resources = db.session.execute(
            select(LearningResource).order_by(LearningResource.level, LearningResource.title)
        ).scalars()
        now = utc_now()
        results = []
        for resource in resources:
            resource_topics = {topic.casefold() for topic in resource.topics}
            if not topics.intersection(resource_topics):
                continue
            verified_at = resource.verified_at
            if verified_at is not None and verified_at.tzinfo is None:
                verified_at = verified_at.replace(tzinfo=now.tzinfo)
            is_fresh = (
                resource.verification_status == "verified"
                and verified_at is not None
                and now - verified_at <= timedelta(days=VERIFICATION_FRESHNESS_DAYS)
            )
            results.append(
                {
                    "id": resource.id,
                    "title": resource.title,
                    "url": resource.url if is_fresh else None,
                    "provider": resource.provider,
                    "resource_type": resource.resource_type,
                    "access_type": resource.access_type,
                    "level": resource.level,
                    "topics": resource.topics,
                    "verified": is_fresh,
                    "requires_verification": not is_fresh,
                }
            )
        return results

    def update_progress(
        self,
        *,
        user_id: int,
        resource_id: int,
        status: str,
        roadmap_id: int | None = None,
    ) -> LearningProgress:
        if not isinstance(status, str) or status not in VALID_PROGRESS_STATES:
            raise ValueError("Invalid learning progress status.")

        resource = db.session.get(LearningResource, resource_id)
        if resource is None:
            raise LookupError("Learning resource does not exist.")
        if resource.verification_status != "verified" or resource.verified_at is None:
            raise ValueError("This resource must be verified before tracking progress.")
        verified_at = resource.verified_at
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=utc_now().tzinfo)
        if utc_now() - verified_at > timedelta(days=VERIFICATION_FRESHNESS_DAYS):
            raise ValueError("This resource's verification has expired.")
        if roadmap_id is not None:
            roadmap = db.session.execute(
                select(CareerRoadmap).where(
                    CareerRoadmap.id == roadmap_id,
                    CareerRoadmap.user_id == user_id,
                )
            ).scalar_one_or_none()
            if roadmap is None:
                raise LookupError("Career roadmap does not exist.")

        progress = db.session.execute(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.resource_id == resource_id,
            )
        ).scalar_one_or_none()
        if progress is None:
            progress = LearningProgress(
                user_id=user_id,
                resource_id=resource_id,
                topic=resource.title,
                status=status,
                roadmap_id=roadmap_id,
            )
            db.session.add(progress)
        else:
            progress.status = status
            if roadmap_id is not None:
                progress.roadmap_id = roadmap_id
        db.session.commit()
        return progress

    def progress_for_user(self, user_id: int) -> dict[int, str]:
        rows = db.session.execute(
            select(LearningProgress.resource_id, LearningProgress.status).where(
                LearningProgress.user_id == user_id,
                LearningProgress.resource_id.is_not(None),
            )
        ).all()
        return {resource_id: status for resource_id, status in rows}


def role_skills(role: str) -> list[str]:
    if role not in CAREER_ROLE_SKILLS:
        raise ValueError("Choose a supported career role.")
    return list(CAREER_ROLE_SKILLS[role])
