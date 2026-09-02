import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from pgvector.sqlalchemy import Vector

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/contract_qa")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    contract_file = Column(Text, unique=True, nullable=False)
    vendor_name = Column(Text)
    agreement_type = Column(Text)
    source = Column(Text, nullable=False)
    full_text = Column(Text, nullable=False)

    chunks = relationship("ContractChunk", back_populates="contract")

class ContractChunk(Base):
    __tablename__ = "contract_chunks"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    section_number = Column(Text)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536))

    contract = relationship("Contract", back_populates="chunks")

class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    draft_answer = Column(Text, nullable=False)
    retrieved_chunks = Column(JSON, nullable=False)
    risk_reason = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    final_answer = Column(Text)
    reviewer_note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)

def init_db():
    # In a real app we'd use Alembic. Here we just create tables.
    import sqlalchemy
    
    db_name = DATABASE_URL.split("/")[-1]
    default_url = DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    
    # 1. Connect to default 'postgres' database to check/create the target DB
    temp_engine = create_engine(default_url)
    # Use autocommit for database creation
    with temp_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(
            sqlalchemy.text(f"SELECT 1 FROM pg_database WHERE datname=:dbname"),
            {"dbname": db_name}
        ).scalar()
        if not exists:
            print(f"Database '{db_name}' not found. Creating database...")
            conn.execute(sqlalchemy.text(f"CREATE DATABASE {db_name}"))
    temp_engine.dispose()
    
    # 2. Connect to the target DB and create vector extension
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        print("Creating pgvector extension if not exists...")
        conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
        
    # 3. Create all tables
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def search_chunks(db: SessionLocal, query_embedding: list, k: int = 5, vendor_name: str = None):
    # Calculate similarity as 1 - cosine_distance
    similarity_expr = (1.0 - ContractChunk.embedding.cosine_distance(query_embedding)).label("similarity")
    
    if vendor_name:
        # Try to filter by vendor name first
        results = (
            db.query(ContractChunk, similarity_expr)
            .join(Contract)
            .filter(Contract.vendor_name.ilike(f"%{vendor_name}%"))
            .order_by(ContractChunk.embedding.cosine_distance(query_embedding))
            .limit(k)
            .all()
        )
        if results:
            return results

    # Fallback to unfiltered search
    return (
        db.query(ContractChunk, similarity_expr)
        .order_by(ContractChunk.embedding.cosine_distance(query_embedding))
        .limit(k)
        .all()
    )
