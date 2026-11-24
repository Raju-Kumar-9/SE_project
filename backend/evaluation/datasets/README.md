# Requirement extraction dataset candidates

The previous session-derived candidate was removed when the interview sessions
were purged. Start new examples from fresh client descriptions. Review every
requirement against its source description, then place corrected examples in
`curated_requirements.jsonl` and set their status to `approved_for_training`
only after your own review.

Do not split requirements from one description across train and evaluation
sets. Keep every requirement from a scenario together to avoid leakage. Keep
the SDLC scorer deterministic; this extraction dataset is not SDLC training
data. Never add compliance mappings or citations to a fine-tuning dataset.

Regenerate a candidate from another completed session with:

```bash
cd backend
python -m evaluation.create_dataset_candidate --session-id SESSION_UUID
```

The Colab notebook is `backend/notebooks/requirement_extraction_qlora_colab.ipynb`.
It intentionally refuses to train on unreviewed data and requires at least 20
reviewed scenarios; aim for 50 or more before treating training as a meaningful
experiment.
