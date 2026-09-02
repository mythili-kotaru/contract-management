import re
import os
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from sqlalchemy.orm import Session
from app.db import Contract, ContractChunk

# Initialize embeddings and LLM
embeddings = GoogleGenerativeAIEmbeddings(model=os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-2"))
llm = ChatGoogleGenerativeAI(model=os.getenv("LLM_MODEL", "gemini-1.5-flash"), temperature=0)

def extract_metadata(text: str):
    # Quick extraction of vendor name and agreement type from the first ~2000 chars
    preview = text[:2000]
    prompt = PromptTemplate.from_template(
        "Extract the 'vendor_name' and 'agreement_type' (e.g. Supply Agreement, Distributor Agreement, SLA, etc) "
        "from the following contract preamble.\n\n{text}\n\n"
        "Return the result exactly as: Vendor Name: <name> | Agreement Type: <type>"
    )
    chain = prompt | llm
    result = chain.invoke({"text": preview}).content
    
    vendor_name = "Unknown"
    agreement_type = "Unknown"
    
    if "Vendor Name:" in result and "|" in result:
        parts = result.split("|")
        vendor_name = parts[0].replace("Vendor Name:", "").strip()
        if "Agreement Type:" in parts[1]:
            agreement_type = parts[1].replace("Agreement Type:", "").strip()
            
    return vendor_name, agreement_type

def split_by_numbered_sections(text: str):
    # Regex to find numbered sections like '1. ', '1.1 ', '1.1. ' at the start of a line
    pattern = re.compile(r'^(?:\d+\.|\d+\.\d+\.?)\s+', re.MULTILINE)
    
    matches = list(pattern.finditer(text))
    chunks = []
    
    if not matches:
        chunks.append(("0", text))
        return chunks
        
    # Text before the first numbered section (preamble/recitals)
    first_match_start = matches[0].start()
    if first_match_start > 0:
        chunks.append(("Preamble", text[:first_match_start].strip()))
        
    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i+1].start() if i + 1 < len(matches) else len(text)
        
        chunk_text = text[start:end].strip()
        section_number = matches[i].group().strip()
        chunks.append((section_number, chunk_text))
        
    return chunks

def ingest_contract(file_path: str, source: str, db: Session):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Strip the 2-line header: "SOURCE:" and "ORIGINAL TITLE:"
    lines = content.split('\n')
    start_idx = 0
    for i, line in enumerate(lines[:10]):
        if line.startswith('==='):
            start_idx = i + 1
            break
    
    contract_text = '\n'.join(lines[start_idx:]).strip()
    
    # Extract metadata
    vendor_name, agreement_type = extract_metadata(contract_text)
    
    # Store contract
    contract = Contract(
        contract_file=os.path.basename(file_path),
        vendor_name=vendor_name,
        agreement_type=agreement_type,
        source=source,
        full_text=contract_text
    )
    db.add(contract)
    db.flush() # flush to get contract.id
    
    # Split into sections
    sections = split_by_numbered_sections(contract_text)
    
    # Sub-split sections if they exceed token limits
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000, # Approx 500 tokens
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    
    db_chunks = []
    texts_to_embed = []
    
    for section_num, section_text in sections:
        sub_chunks = text_splitter.split_text(section_text)
        for sub_chunk in sub_chunks:
            db_chunks.append(ContractChunk(
                contract_id=contract.id,
                section_number=section_num,
                chunk_text=sub_chunk
            ))
            texts_to_embed.append(sub_chunk)
            
    # Compute embeddings in batch
    embeds = embeddings.embed_documents(texts_to_embed)
    
    for i, db_chunk in enumerate(db_chunks):
        db_chunk.embedding = embeds[i]
        db.add(db_chunk)
        
    db.commit()
    return contract.id
