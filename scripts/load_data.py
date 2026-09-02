import os
import glob
from sqlalchemy.orm import Session
from app.db import init_db, SessionLocal
from app.ingestion import ingest_contract

def load_data():
    # Initialize DB (create tables)
    print("Initializing database tables...")
    init_db()
    
    db: Session = SessionLocal()
    try:
        base_dir = os.path.join(os.path.dirname(__file__), "..", "contract-qa-sample-data")
        
        # Load CUAD contracts
        cuad_dir = os.path.join(base_dir, "real_contracts_cuad", "contracts")
        cuad_files = glob.glob(os.path.join(cuad_dir, "*.txt"))
        print(f"Found {len(cuad_files)} CUAD contracts.")
        for file in cuad_files:
            print(f"Ingesting {os.path.basename(file)} (CUAD)...")
            ingest_contract(file, source="cuad", db=db)
            
        # Load Synthetic contracts
        synth_dir = os.path.join(base_dir, "synthetic_vendor_slas", "contracts")
        synth_files = glob.glob(os.path.join(synth_dir, "*.txt"))
        print(f"Found {len(synth_files)} synthetic contracts.")
        for file in synth_files:
            print(f"Ingesting {os.path.basename(file)} (Synthetic)...")
            ingest_contract(file, source="synthetic", db=db)
            
        print("Data ingestion complete!")
    except Exception as e:
        print(f"Error during ingestion: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    load_data()
