import os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langfuse import observe
from app.db import get_db, ReviewQueue, Contract, ContractChunk
from app.graph import app_graph

app = FastAPI(title="Vendor Contract Assistant")

# Mount Static Files & Serve UI
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def serve_ui():
    return FileResponse("static/index.html")

@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    contracts_count = db.query(Contract).count()
    chunks_count = db.query(ContractChunk).count()
    pending_reviews = db.query(ReviewQueue).filter(ReviewQueue.status == "pending").count()
    return {
        "contracts_count": contracts_count,
        "chunks_count": chunks_count,
        "pending_reviews": pending_reviews
    }

@app.get("/contracts")
def list_contracts(db: Session = Depends(get_db)):
    contracts = db.query(Contract.id, Contract.vendor_name, Contract.contract_file, Contract.agreement_type, Contract.source).all()
    return [
        {
            "id": c.id,
            "vendor_name": c.vendor_name,
            "contract_file": c.contract_file,
            "agreement_type": c.agreement_type,
            "source": c.source
        }
        for c in contracts
    ]

class QuestionRequest(BaseModel):
    question: str

class DecisionRequest(BaseModel):
    decision: str  # approve, edit, reject
    final_answer: str = None
    note: str = None

@app.post("/questions")
@observe(name="submit-question")
def ask_question(request: QuestionRequest, db: Session = Depends(get_db)):
    try:
        # Execute LangGraph
        inputs = {"question": request.question}
        result = app_graph.invoke(inputs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline Execution Error: {str(e)}")
    
    status = result.get("status")
    risk_reason = result.get("risk_reason", "")

    if status == "ambiguous":
        return {
            "type": "clarifying_question",
            "clarifying_question": result.get("clarifying_question")
        }
    elif status == "queue_for_review":
        # Save to review queue database
        review_item = ReviewQueue(
            question=request.question,
            draft_answer=result.get("draft_answer") or "",
            retrieved_chunks=result.get("retrieved_chunks") or [],
            risk_reason=risk_reason,
            status="pending"
        )
        db.add(review_item)
        db.commit()
        db.refresh(review_item)
        
        return {
            "type": "pending_review",
            "pending_review_id": review_item.id,
            "risk_reason": risk_reason
        }
    else:  # auto_answer
        return {
            "type": "auto_answer",
            "answer": result.get("draft_answer"),
            "retrieved_chunks": result.get("retrieved_chunks") or []
        }

@app.get("/review-queue")
def list_review_queue(db: Session = Depends(get_db)):
    items = db.query(ReviewQueue).filter(ReviewQueue.status == "pending").all()
    return items

@app.get("/review-queue/{id}")
def get_review_item(id: int, db: Session = Depends(get_db)):
    item = db.query(ReviewQueue).filter(ReviewQueue.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item

@app.post("/review-queue/{id}/decision")
def submit_decision(id: int, request: DecisionRequest, db: Session = Depends(get_db)):
    item = db.query(ReviewQueue).filter(ReviewQueue.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
        
    decision = request.decision.lower()
    if decision not in ["approve", "edit", "reject"]:
        raise HTTPException(status_code=400, detail="Invalid decision. Must be approve, edit, or reject")
        
    item.status = f"{decision}d" if decision in ["approve", "reject"] else "edited"
    item.resolved_at = datetime.utcnow()
    item.reviewer_note = request.note
    
    if decision in ["approve", "edit"]:
        if decision == "approve":
            item.final_answer = item.draft_answer
        else:
            if not request.final_answer:
                raise HTTPException(status_code=400, detail="final_answer is required for edit decision")
            item.final_answer = request.final_answer
            
    db.commit()
    db.refresh(item)
    
    return {
        "status": "resolved",
        "item_id": item.id,
        "new_status": item.status,
        "final_answer": item.final_answer
    }
