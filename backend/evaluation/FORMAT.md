# Phase 5 evaluation data format

The benchmark is a JSONL file with one hand-labeled row per `scenario_id`.
Each prediction row uses the same `scenario_id` and contains the pipeline's
`requirements` array plus its `sdlc_recommendation.ranked_scores` array.

```json
{"scenario_id":"loan-app-001","requirements":[{"source_slot":"repayment_emi_terms","statement":"The system shall show the applicant the repayment schedule and EMI amount before submission."}],"sdlc_ranking":["Agile + DevSecOps Hybrid","DevSecOps","Agile","V-Model","Spiral","Waterfall"]}
```

Requirement matching is one-to-one, requires the same `source_slot`, and uses
token F1 >= 0.5 by default. Record enough benchmark scenarios with varied
consumer-loan workflows; the example above documents format and is not a
statistically meaningful evaluation set. Review unmatched predictions before
calling them hallucinations: `hallucination_proxy` is a benchmark-based proxy.

Prediction JSONL example:

```json
{"scenario_id":"loan-app-001","requirements":[{"source_slot":"repayment_emi_terms","statement":"The system shall display an EMI repayment schedule before application submission."}],"sdlc_recommendation":{"ranked_scores":[{"model":"Agile + DevSecOps Hybrid","score_percent":82.1},{"model":"DevSecOps","score_percent":79.0}]}}
```

Human-reviewed SDLC narration labels, if supplied to the exporter, use one
JSONL row each:

```json
{"human_reviewed":true,"input":{"ranked_scores":[{"model":"DevSecOps","score_percent":81.0}],"factors_used":{"security_risk":{"rating":5}}},"target":{"narration":"DevSecOps fits the high security needs and supports frequent delivery with automated checks."}}
```

Only approved requirements from session IDs explicitly listed in a consent
JSON array are exported for extraction and classification. Reviewer approval
alone is not training consent. The exporter selects only the relevant source
slot, redacts obvious email/long-number identifiers, and does not export
compliance mappings, citations, or confidence. Manually inspect and de-identify
the resulting dataset before use; automated redaction cannot reliably detect
names or every form of sensitive data. Narration text must be separately
human-reviewed; the exporter never uses generated narration as a trusted target.
