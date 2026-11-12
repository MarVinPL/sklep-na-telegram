import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import User, WebAuthnChallenge
from app.routers.passkeys import _consume_challenge, _get_or_create_user

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


@pytest.fixture
def postgres_session_factory():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_postgres_allows_only_one_parallel_challenge_consumption(postgres_session_factory) -> None:
    with postgres_session_factory() as setup:
        user = User(telegram_user_id="pg-challenge-race")
        setup.add(user)
        setup.flush()
        challenge = WebAuthnChallenge(
            id="pg-challenge-race",
            user_id=user.id,
            purpose="authentication",
            challenge=b"one-time-challenge",
            context_hash=__import__("hashlib").sha256(b"init-data").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )
        setup.add(challenge)
        setup.commit()
        user_id = user.id

    barrier = Barrier(2)

    def consume():
        with postgres_session_factory() as session:
            barrier.wait(timeout=10)
            try:
                return _consume_challenge(
                    session, "pg-challenge-race", user_id, "authentication", "init-data"
                )
            except HTTPException:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))

    assert results.count(b"one-time-challenge") == 1
    assert results.count(None) == 1


def test_postgres_concurrent_telegram_user_creation_recovers_unique_race(
    postgres_session_factory,
) -> None:
    barrier = Barrier(2)

    def create_user():
        with postgres_session_factory() as session:
            barrier.wait(timeout=10)
            user = _get_or_create_user(session, "pg-user-create-race")
            session.commit()
            return user.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        user_ids = list(pool.map(lambda _: create_user(), range(2)))

    assert user_ids[0] == user_ids[1]
    with postgres_session_factory() as session:
        matches = session.scalars(
            select(User).where(User.telegram_user_id == "pg-user-create-race")
        ).all()
        assert len(matches) == 1
