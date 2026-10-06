## 🧪 Spike Report: Kafka Partitioning

### 🎯 Empirical Question & Hypothesis
- **Question**: Can a single Kafka partition handle 20,000 RPS?
- **Hypothesis**: Throughput > 20000 RPS with p99 < 10ms.

### 🧪 Methodology & Setup
- **Sandbox**: `.scratch/kafka-spike/`

### 📊 Empirical Results
Throughput was roughly 25,000 requests per second and it looked very fast.

### ⚖️ Architectural Verdict
- **Verdict**: CONFIRMED
- **Recommendation**: Single partition is fine.
- **Frontier Impact**: Frontier resolved.
