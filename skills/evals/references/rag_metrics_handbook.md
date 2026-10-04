# RAG Evaluation Handbook

Framework for decomposing and evaluating Retrieval-Augmented Generation (RAG) pipelines.

---

## 1. Decomposing RAG Failures

Never evaluate a RAG pipeline as a single monolith. Always isolate:
1. **Retrieval Stage**: Did the retriever fetch the necessary context?
2. **Generation Stage**: Did the LLM faithfully synthesize an answer given the retrieved context?

```text
User Query
    │
    ▼
[Retriever] ──▶ Evaluated via: Hit@K, MRR, Context Relevance
    │
    ▼ Retrieved Chunks
[Generator] ──▶ Evaluated via: Faithfulness (Hallucination), Answer Relevance
    │
    ▼
Final Output
```

---

## 2. Retrieval Metrics

- **Context Relevance**: Fraction of retrieved chunks that contain information pertinent to the query.
  - *Code/Judge check*: Binary check per chunk — does chunk contain necessary facts for the query?
- **Hit@K / Recall@K**: Did at least one chunk containing the ground truth answer appear in the top $K$ results?
- **Mean Reciprocal Rank (MRR)**: Evaluates position: $\frac{1}{\text{rank}}$ of the first relevant chunk.

---

## 3. Generation Metrics

- **Faithfulness (Groundedness)**: Can all claims made in the generation be substantiated by the retrieved context?
  - *Method*: Split the generated answer into atomic claims/propositions. Verify each claim against retrieved chunks. If any claim cannot be substantiated, score is FAIL (hallucination).
- **Answer Relevance**: Does the generated answer address the user's specific query without evading or drifting off-topic?
- **Negative Rejection (I Don't Know Test)**: When context does *not* contain the answer, does the model refuse rather than hallucinate?
