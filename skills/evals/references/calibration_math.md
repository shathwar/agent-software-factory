# Evaluator Calibration & Rogan-Gladen Statistics

Mathematical formulations for evaluating LLM judges against human ground truth and correcting production prevalence estimates.

---

## 1. True Positive Rate (TPR) and True Negative Rate (TNR)

Given human ground-truth labels and evaluator predictions:

$$\text{TPR} = \frac{\text{TP}}{\text{TP} + \text{FN}} = \frac{P(\text{Judge Pass} \mid \text{Human Pass})}{1}$$

$$\text{TNR} = \frac{\text{TN}}{\text{TN} + \text{FP}} = \frac{P(\text{Judge Fail} \mid \text{Human Fail})}{1}$$

### Why Accuracy Fails
When test data is imbalanced (e.g., 90% of real traces Pass and 10% Fail), a naive judge that outputs "Pass" 100% of the time achieves **90% raw accuracy**, despite having a **0% TNR** (catches zero failures). TPR and TNR decouple performance on positive and negative cases.

- **Target Threshold**: $\text{TPR} \ge 0.90$ AND $\text{TNR} \ge 0.90$
- **Minimum Operational Threshold**: $\text{TPR} \ge 0.80$ AND $\text{TNR} \ge 0.80$

---

## 2. Rogan-Gladen Bias Correction

When an imperfect judge runs over a large unlabeled production dataset, the observed pass rate $p_{\text{obs}}$ is biased by the judge's false positives and false negatives.

The Rogan-Gladen estimator recovers the unbiased underlying true success rate $\hat{\theta}$:

$$\hat{\theta} = \frac{p_{\text{obs}} + \text{TNR} - 1}{\text{TPR} + \text{TNR} - 1}$$

### Worked Example:
- Held-out test set calibration: $\text{TPR} = 0.92$, $\text{TNR} = 0.88$
- Observed production pass rate over 10,000 traces: $p_{\text{obs}} = 0.80$
- Calculation:
  $$\hat{\theta} = \frac{0.80 + 0.88 - 1.0}{0.92 + 0.88 - 1.0} = \frac{0.68}{0.80} = 0.85$$
- The true production success rate is **85%**, not the raw 80% reported by the judge.

---

## 3. Bootstrap 95% Confidence Intervals

To calculate the confidence bounds for $\hat{\theta}$:
1. Resample test set pairs $(y_i, \hat{y}_i)$ with replacement $B = 2,000$ times.
2. For each sample $b$, recompute $\text{TPR}_b$ and $\text{TNR}_b$.
3. Compute $\hat{\theta}_b = \frac{p_{\text{obs}} + \text{TNR}_b - 1}{\text{TPR}_b + \text{TNR}_b - 1}$, clipping to $[0, 1]$.
4. The 95% CI is defined by the 2.5th and 97.5th percentiles of the bootstrap distribution.

Run this calculation deterministically via:
```bash
python3 "$SKILLS_DIR/evals/scripts/score_calibration.py" --input test_results.jsonl --p-obs 0.80
```
