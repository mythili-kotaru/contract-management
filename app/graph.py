import os
import re
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langfuse import observe
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import PromptTemplate
from app.db import SessionLocal, Contract, ContractChunk, search_chunks
from app.risk_router import assess_confidence_and_risk

# Initialize OpenAI
embeddings = OpenAIEmbeddings(model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))
llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0)

class AgentState(TypedDict):
    question: str
    contract_file: Optional[str]
    vendor_name: Optional[str]
    retrieved_chunks: Optional[List[Dict[str, Any]]]
    draft_answer: Optional[str]
    clarifying_question: Optional[str]
    status: str  # "ambiguous" | "clear" | "auto_answer" | "hitl_review"
    risk_reason: Optional[str]
    top_score: Optional[float]

@observe(name="check_ambiguity")
def check_ambiguity_node(state: AgentState) -> Dict[str, Any]:
    question = state["question"]
    contract_file = state.get("contract_file")
    db = SessionLocal()
    
    try:
        matched_vendor = None
        if contract_file:
            contract = db.query(Contract).filter(Contract.contract_file == contract_file).first()
            if contract:
                matched_vendor = contract.vendor_name
                
        if not matched_vendor:
            # Get all vendor names from DB to see if one is explicitly mentioned
            vendors = db.query(Contract.vendor_name).distinct().all()
            vendors = [v[0] for v in vendors if v[0]]
            for v in vendors:
                v_clean = re.sub(r'\b(llc|inc|ltd|co|corp|corporation|solutions|partners)\b', '', v, flags=re.IGNORECASE).strip()
                if (v_clean and v_clean.lower() in question.lower()) or v.lower() in question.lower():
                    matched_vendor = v
                    break
                
        # Perform retrieval
        query_embedding = embeddings.embed_query(question)
        results = search_chunks(db, query_embedding, k=5, vendor_name=matched_vendor)
        
        if not results:
            return {
                "status": "clear",
                "retrieved_chunks": [],
                "vendor_name": matched_vendor,
                "top_score": 0.0
            }
            
        # Group by contract and find max score for each
        contract_scores = {}
        for chunk, score in results:
            c_id = chunk.contract_id
            c_name = chunk.contract.vendor_name or "Unknown"
            if c_id not in contract_scores or score > contract_scores[c_id]["score"]:
                contract_scores[c_id] = {"name": c_name, "score": float(score)}
                
        sorted_contracts = sorted(contract_scores.values(), key=lambda x: x["score"], reverse=True)
        
        # Ambiguity condition check
        is_ambiguous = False
        clarifying_question = None
        
        # If no vendor named, and top-k spans 3+ contracts within 0.05 similarity
        if not matched_vendor and len(sorted_contracts) >= 3:
            top_score = sorted_contracts[0]["score"]
            third_score = sorted_contracts[2]["score"]
            if (top_score - third_score) <= 0.05:
                is_ambiguous = True
                candidate_names = [c["name"] for c in sorted_contracts[:3]]
                clarifying_question = f"Which vendor's contract are you referring to? Candidates: {', '.join(candidate_names[:-1])}, or {candidate_names[-1]}?"
                
        # Prepare retrieved chunks dict
        chunks_list = []
        for chunk, score in results:
            chunks_list.append({
                "chunk_id": chunk.id,
                "contract_file": chunk.contract.contract_file,
                "vendor_name": chunk.contract.vendor_name,
                "agreement_type": chunk.contract.agreement_type,
                "section_number": chunk.section_number,
                "chunk_text": chunk.chunk_text,
                "score": float(score)
            })
            
        if is_ambiguous:
            return {
                "status": "ambiguous",
                "clarifying_question": clarifying_question,
                "retrieved_chunks": chunks_list,
                "vendor_name": None,
                "top_score": float(results[0][1])
            }
        else:
            return {
                "status": "clear",
                "retrieved_chunks": chunks_list,
                "vendor_name": matched_vendor,
                "top_score": float(results[0][1])
            }
    finally:
        db.close()

def ask_clarifying_question_node(state: AgentState) -> Dict[str, Any]:
    # Terminal node for ambiguity
    return {}

@observe(name="retrieve")
def retrieve_node(state: AgentState) -> Dict[str, Any]:
    # Already retrieved in check_ambiguity_node to avoid double DB calls.
    return {}

@observe(name="generate")
def generate_node(state: AgentState) -> Dict[str, Any]:
    question = state["question"]
    chunks = state.get("retrieved_chunks", [])
    
    if not chunks:
        return {"draft_answer": "Not found in the provided context."}
        
    context_str = ""
    for i, chunk in enumerate(chunks):
        context_str += f"[{i+1}] File: {chunk['contract_file']} | Section: {chunk['section_number']}\n{chunk['chunk_text']}\n\n"
        
    prompt = PromptTemplate.from_template(
        "You are an expert contract review assistant. Answer the user's question based strictly on the retrieved chunks below. "
        "Cite the section number of the contract for your assertions. "
        "If the context does not contain enough information to answer the question, state exactly: "
        "'not found in the provided context' and do not extrapolate.\n\n"
        "Retrieved Chunks:\n{context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    )
    
    chain = prompt | llm
    
    # Get langchain callback handler
    from langfuse.langchain import CallbackHandler
    handler = CallbackHandler()
    response = chain.invoke(
        {"context": context_str, "question": question},
        config={"callbacks": [handler]}
    )
    
    return {"draft_answer": response.content}

@observe(name="assess_risk")
def assess_risk_node(state: AgentState) -> Dict[str, Any]:
    question = state["question"]
    top_score = state.get("top_score", 0.0)
    
    decision, reason = assess_confidence_and_risk(question, top_score)
    
    return {
        "status": decision,
        "risk_reason": reason
    }

# Build LangGraph
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("check_ambiguity", check_ambiguity_node)
workflow.add_node("ask_clarifying_question", ask_clarifying_question_node)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)
workflow.add_node("assess_risk", assess_risk_node)

# Set Entry Point
workflow.set_entry_point("check_ambiguity")

# Conditional Router after ambiguity check
def route_after_ambiguity(state: AgentState):
    if state["status"] == "ambiguous":
        return "ask_clarifying_question"
    return "retrieve"

workflow.add_conditional_edges(
    "check_ambiguity",
    route_after_ambiguity,
    {
        "ask_clarifying_question": "ask_clarifying_question",
        "retrieve": "retrieve"
    }
)

# Normal edges
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", "assess_risk")

# Terminal nodes
workflow.add_edge("ask_clarifying_question", END)

def route_after_risk(state: AgentState):
    # assess_risk sets status to either 'auto_answer' or 'queue_for_review'
    return END

workflow.add_conditional_edges(
    "assess_risk",
    route_after_risk,
    {
        END: END
    }
)

# Compile graph
app_graph = workflow.compile()
