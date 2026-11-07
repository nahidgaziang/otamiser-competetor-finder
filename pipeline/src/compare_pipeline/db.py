from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from compare_pipeline.config import settings

Base = declarative_base()

# Role-specific engines
engine_admin = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
engine_migrator = create_engine(settings.DATABASE_URL_MIGRATOR, pool_pre_ping=True)
engine_pipeline = create_engine(settings.DATABASE_URL_PIPELINE, pool_pre_ping=True)
engine_web = create_engine(settings.DATABASE_URL_WEB, pool_pre_ping=True)

# Session makers
AdminSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_admin)
MigratorSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine_migrator
)
PipelineSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine_pipeline
)
WebSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_web)


@contextmanager
def get_admin_session() -> Generator[Session, None, None]:
    session = AdminSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_migrator_session() -> Generator[Session, None, None]:
    session = MigratorSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_pipeline_session() -> Generator[Session, None, None]:
    session = PipelineSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_web_session() -> Generator[Session, None, None]:
    session = WebSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
