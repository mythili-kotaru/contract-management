import os
import csv
import re
import json
from langsmith import Client, evaluate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from app.graph import app_graph

# Initialize Langsmith Client
client = Client()
llm = ChatGoogleGenerativeAI(model=os.getenv("LLM_MODEL", "gemini-1.5-flash"), temperature=0)

def load_csv_to_langsmith(csv_path: str, dataset_name: str, has_risk_level: bool):
    if client.has_dataset(dataset_name=dataset_name):
        print(f"Deleting existing dataset '{dataset_name}' to update schema...")
        try:
            client.delete_dataset(dataset_name=dataset_name)
        except Exception as e:
            print(f"Could not delete dataset: {e}")

    print(f"Creating LangSmith dataset '{dataset_name}' from {csv_path}...")
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=f"Evaluation dataset loaded from {os.path.basename(csv_path)}"
    )

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Prepare inputs with contract_file context
            inputs = {
                "question": row["question"],
                "contract_file": row["contract_file"]
            }
            
            # Prepare outputs / metadata
            outputs = {
                "ground_truth_answer": row["ground_truth_answer"],
                "contract_file": row["contract_file"],
                "category": row["category"]
            }
            if has_risk_level:
                outputs["risk_level"] = row["risk_level"]

            client.create_example(
                inputs=inputs,
                outputs=outputs,
                dataset_id=dataset.id
            )
            
    print(f"Dataset '{dataset_name}' created successfully with examples.")
    return dataset

# Pipeline execution wrapper for LangSmith evaluation
def run_pipeline(inputs: dict) -> dict:
    question = inputs["question"]
    contract_file = inputs.get("contract_file")
    result = app_graph.invoke({"question": question, "contract_file": contract_file})
    return {
        "answer": result.get("draft_answer") or result.get("clarifying_question"),
        "status": result.get("status"),
        "retrieved_chunks": result.get("retrieved_chunks") or []
    }

# Evaluator 1: Correctness (LLM Graded)
def correctness_evaluator(run, example) -> dict:
    prediction = run.outputs.get("answer") or ""
    reference = example.outputs.get("ground_truth_answer") or ""
    
    prompt = PromptTemplate.from_template(
        "Compare the predicted answer to the ground truth reference answer. "
        "Grade the correctness of the predicted answer on a scale from 0.0 to 1.0, where 1.0 is fully correct and covers all facts, "
        "0.5 is partially correct, and 0.0 is incorrect.\n\n"
        "Predicted Answer: {prediction}\n"
        "Reference Answer: {reference}\n\n"
        "Format: Score: <score> | Reason: <reason>"
    )
    chain = prompt | llm
    res = chain.invoke({"prediction": prediction, "reference": reference}).content
    
    score = 0.0
    try:
        score_match = re.search(r"Score:\s*([0-9.]+)", res)
        if score_match:
            score = float(score_match.group(1))
    except Exception as e:
        print(f"Error parsing correctness score: {e}")
        
    return {"key": "correctness", "score": score, "comment": res}

# Evaluator 2: Faithfulness (Word overlap / substring check)
def faithfulness_evaluator(run, example) -> dict:
    answer = run.outputs.get("answer") or ""
    reference = example.outputs.get("ground_truth_answer") or ""
    chunks = run.outputs.get("retrieved_chunks") or []
    
    cited_sections = re.findall(r"(?:Section\s+)?(\d+(?:\.\d+)*)", answer)
    if not cited_sections:
        cited_sections = [c["section_number"] for c in chunks]
        
    for sec in cited_sections:
        for chunk in chunks:
            if chunk["section_number"] == sec or sec in chunk["section_number"]:
                ref_clean = re.sub(r'[^\w\s]', '', reference.lower()).strip()
                chunk_clean = re.sub(r'[^\w\s]', '', chunk["chunk_text"].lower()).strip()
                
                if ref_clean in chunk_clean:
                    return {"key": "faithfulness", "score": 1.0}
                    
                ref_words = set(ref_clean.split())
                chunk_words = set(chunk_clean.split())
                if ref_words and len(ref_words.intersection(chunk_words)) / len(ref_words) >= 0.5:
                    return {"key": "faithfulness", "score": 1.0}
                    
    return {"key": "faithfulness", "score": 0.0}

# Evaluator 3: Risk Router decision match (for Synthetic only)
def risk_router_evaluator(run, example) -> dict:
    status = run.outputs.get("status")
    labeled_risk = example.outputs.get("risk_level")
    
    if not labeled_risk:
        # Not applicable for CUAD dataset
        return {"key": "risk_match", "score": 1.0}
        
    expected_status = "auto_answer" if labeled_risk == "auto" else "queue_for_review"
    score = 1.0 if status == expected_status else 0.0
    return {
        "key": "risk_match",
        "score": score,
        "comment": f"Predicted: {status} | Expected: {expected_status} (from {labeled_risk})"
    }

def run_evaluations():
    base_dir = os.path.join(os.path.dirname(__file__), "..", "contract-qa-sample-data")
    
    # 1. Evaluate Synthetic Dataset
    synth_csv = os.path.join(base_dir, "synthetic_vendor_slas", "eval_questions_synthetic.csv")
    load_csv_to_langsmith(synth_csv, "contract-qa-synthetic", has_risk_level=True)
    
    print("Running evaluation on contract-qa-synthetic...")
    results_synth = evaluate(
        run_pipeline,
        data="contract-qa-synthetic",
        evaluators=[correctness_evaluator, faithfulness_evaluator, risk_router_evaluator],
        experiment_prefix="synthetic-eval"
    )
    
    # Print summary statistics
    # LangSmith evaluate returns an ExperimentResults object
    print("\n=== Synthetic Dataset Evaluation Results ===")
    print(f"Project Metadata: {getattr(results_synth, 'project_metadata', 'N/A')}")
    
    # Calculate local stats if possible
    correctness_scores = []
    faithfulness_scores = []
    risk_match_scores = []
    
    # We can inspect the results from Langsmith Experiment
    for row in results_synth:
        # Get evaluation results
        for fb in row["evaluation_results"]["results"]:
            if fb.key == "correctness" and fb.score is not None:
                correctness_scores.append(fb.score)
            elif fb.key == "faithfulness" and fb.score is not None:
                faithfulness_scores.append(fb.score)
            elif fb.key == "risk_match" and fb.score is not None:
                risk_match_scores.append(fb.score)
                
    if correctness_scores:
        print(f"Average Correctness: {sum(correctness_scores)/len(correctness_scores):.2f}")
    if faithfulness_scores:
        print(f"Average Faithfulness: {sum(faithfulness_scores)/len(faithfulness_scores):.2f}")
    if risk_match_scores:
        print(f"Risk Router Match Accuracy: {sum(risk_match_scores)/len(risk_match_scores):.2%}")
        
    # 2. Evaluate CUAD Dataset
    cuad_csv = os.path.join(base_dir, "real_contracts_cuad", "eval_questions_cuad.csv")
    load_csv_to_langsmith(cuad_csv, "contract-qa-cuad", has_risk_level=False)
    
    print("\nRunning evaluation on contract-qa-cuad...")
    results_cuad = evaluate(
        run_pipeline,
        data="contract-qa-cuad",
        evaluators=[correctness_evaluator, faithfulness_evaluator],
        experiment_prefix="cuad-eval"
    )
    
    print("\n=== CUAD Dataset Evaluation Results ===")
    cuad_correctness = []
    cuad_faithfulness = []
    
    for row in results_cuad:
        for fb in row["evaluation_results"]["results"]:
            if fb.key == "correctness" and fb.score is not None:
                cuad_correctness.append(fb.score)
            elif fb.key == "faithfulness" and fb.score is not None:
                cuad_faithfulness.append(fb.score)
                
    if cuad_correctness:
        print(f"Average Correctness: {sum(cuad_correctness)/len(cuad_correctness):.2f}")
    if cuad_faithfulness:
        print(f"Average Faithfulness: {sum(cuad_faithfulness)/len(cuad_faithfulness):.2f}")

if __name__ == "__main__":
    run_evaluations()
