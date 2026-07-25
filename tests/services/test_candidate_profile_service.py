"""
Service tests for CandidateProfileService.

Real Postgres DB, but upload_file / extract_text / generate_embedding /
upsert_candidate_embedding / generate_presigned_download_url are all
mocked — this service's job is orchestration and validation (file type,
size, ownership of the profile), not actually talking to MinIO, running
a PDF parser, or computing real embeddings.
"""

import io
import uuid

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.models.candidate_profile import CandidateProfile
from app.models.user import User
from app.repositories.candidate_profile_repository import CandidateProfileRepository
from app.schemas.candidate_profile import CandidateProfileUpsert
from app.services.candidate_profile_service import (
    MAX_RESUME_SIZE_BYTES,
    CandidateProfileNotFoundError,
    CandidateProfileService,
    InvalidResumeFileError,
)


def _make_user(db_session: Session, **overrides) -> User:
    defaults = {
        "email": f"{uuid.uuid4()}@test.com",
        "hashed_password": "not-a-real-hash",
        "full_name": "Test Candidate",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_upload_file(
    content: bytes = b"%PDF-1.4 fake pdf content",
    filename: str = "resume.pdf",
    content_type: str = "application/pdf",
) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.fixture(autouse=True)
def _mock_search_indexing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Every test gets no-op mocks for the search-indexing pipeline
    (extract_text / generate_embedding / upsert_candidate_embedding) and
    the S3 upload — tests that specifically care about one of these
    override it individually.
    """
    monkeypatch.setattr(
        "app.services.candidate_profile_service.extract_text", lambda *_: "extracted resume text"
    )
    monkeypatch.setattr(
        "app.services.candidate_profile_service.generate_embedding", lambda *_: [0.1, 0.2, 0.3]
    )
    monkeypatch.setattr(
        "app.services.candidate_profile_service.upsert_candidate_embedding", lambda *_: None
    )
    monkeypatch.setattr(
        "app.services.candidate_profile_service.upload_file", lambda *_, **__: None
    )


class TestCandidateProfileServiceUpsert:
    def test_upsert_creates_profile_when_none_exists(self, db_session: Session) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)

        profile = service.upsert_own_profile(
            user.id, CandidateProfileUpsert(headline="New Headline")
        )

        assert profile.id is not None
        assert profile.headline == "New Headline"

    def test_upsert_updates_existing_profile_instead_of_duplicating(
        self, db_session: Session
    ) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        first = service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="First"))

        second = service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Second"))

        assert second.id == first.id
        assert second.headline == "Second"

    def test_upsert_partial_update_only_changes_provided_fields(
        self, db_session: Session
    ) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(
            user.id, CandidateProfileUpsert(headline="Original", location="Original City")
        )

        updated = service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Updated"))

        assert updated.headline == "Updated"
        assert updated.location == "Original City"


class TestCandidateProfileServiceGet:
    def test_get_profile_raises_when_none_exists(self, db_session: Session) -> None:
        service = CandidateProfileService(db_session)

        with pytest.raises(CandidateProfileNotFoundError):
            service.get_profile_by_user_id(uuid.uuid4())


class TestCandidateProfileServiceUploadResume:
    def test_upload_resume_raises_when_no_profile_exists(self, db_session: Session) -> None:
        service = CandidateProfileService(db_session)

        with pytest.raises(CandidateProfileNotFoundError):
            service.upload_resume(uuid.uuid4(), _make_upload_file())

    def test_upload_resume_rejects_disallowed_content_type(self, db_session: Session) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Has Profile"))

        bad_file = _make_upload_file(content_type="image/png", filename="not-a-resume.png")

        with pytest.raises(InvalidResumeFileError):
            service.upload_resume(user.id, bad_file)

    def test_upload_resume_rejects_oversized_file(self, db_session: Session) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Has Profile"))

        oversized_content = b"x" * (MAX_RESUME_SIZE_BYTES + 1)
        oversized_file = _make_upload_file(content=oversized_content)

        with pytest.raises(InvalidResumeFileError):
            service.upload_resume(user.id, oversized_file)

    def test_upload_resume_succeeds_and_updates_profile(self, db_session: Session) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Has Profile"))

        updated = service.upload_resume(user.id, _make_upload_file(filename="my_resume.pdf"))

        assert updated.resume_filename == "my_resume.pdf"
        assert updated.resume_object_key is not None
        # Server generates the storage key — must not just be the raw
        # client-supplied filename, which would allow path traversal /
        # predictable/colliding object keys across users.
        assert updated.resume_object_key != "my_resume.pdf"
        assert str(user.id) in updated.resume_object_key

    def test_upload_resume_succeeds_even_when_search_indexing_fails(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        _index_resume_for_search is explicitly documented as best-effort:
        a failure there must NOT prevent the resume upload itself from
        succeeding. This test forces generate_embedding to raise and
        confirms upload_resume still returns normally.
        """

        def _boom(*_args, **_kwargs):
            raise RuntimeError("Chroma is unreachable")

        monkeypatch.setattr(
            "app.services.candidate_profile_service.generate_embedding", _boom
        )

        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Has Profile"))

        updated = service.upload_resume(user.id, _make_upload_file())

        assert updated.resume_filename is not None


class TestCandidateProfileServiceResumeDownloadUrl:
    def test_get_resume_download_url_raises_when_no_profile(self, db_session: Session) -> None:
        service = CandidateProfileService(db_session)

        with pytest.raises(CandidateProfileNotFoundError):
            service.get_resume_download_url(uuid.uuid4())

    def test_get_resume_download_url_raises_when_no_resume_uploaded(
        self, db_session: Session
    ) -> None:
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="No Resume Yet"))

        with pytest.raises(CandidateProfileNotFoundError):
            service.get_resume_download_url(user.id)

    def test_get_resume_download_url_returns_presigned_url(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.candidate_profile_service.generate_presigned_download_url",
            lambda _key: "https://minio.local/presigned-fake-url",
        )
        user = _make_user(db_session)
        service = CandidateProfileService(db_session)
        service.upsert_own_profile(user.id, CandidateProfileUpsert(headline="Has Profile"))
        service.upload_resume(user.id, _make_upload_file())

        url = service.get_resume_download_url(user.id)

        assert url == "https://minio.local/presigned-fake-url"
