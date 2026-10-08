# RI-4.10 — Title-Rule Classification and Grounded LLM Extraction

## Objective

Provide a local, measurable default for the RI-3 classification and RI-3.1 extraction ports:

- classification by deterministic heading rules from an operator profile;
- field extraction by a locally served language model over OCR text, where only values found verbatim in the source become `PRESENT`.

No contract changes. Both components plug into the existing ports (`ClassifierAdapter`, `ExtractorAdapter`, `ProviderInvoker`) and pass through the existing taxonomy, schema, evidence and invocation checks.

## Title-rule classifier

`application/title_rules.py` — `TitleRuleClassifier`, configured by a `TitleRuleProfile` loaded from JSON (default: `deploy/classification-profiles/title-rules-id-en.json`).

- Rules are ordered `(pattern, document_type)` pairs, matched case-insensitively against the first `heading_blocks` text blocks of page 1 in reading order. The first matching rule wins, so specific headings (for example `faktur pajak`, `pesanan`) are listed before generic ones (`invoice`).
- Blocks are joined before matching because OCR often splits a heading across lines; every block the match spans is cited as `TEXT_BLOCK` evidence with its text as quote.
- No match produces no candidate, so `classify_document` abstains to `UNKNOWN`. Rules cannot emit `UNKNOWN`, and their document types must exist in the selected taxonomy version.
- Rules are configuration. Document content never adds, removes or reorders rules. Tenant-specific vocabularies belong in additional profiles, not code branches.

## Grounded LLM extractor

`application/llm_extraction.py` — `LlmFieldExtractor`.

- Sends a provider-neutral request (document type, schema fields, text blocks in reading order) through `invoke_provider`, so execution class, egress, size limits and stable failure codes are enforced by RI-3.7.
- The model answer is a claim. A value is `PRESENT` only when it occurs in a source text block (whitespace-tolerant). The raw value and evidence quote are the exact source span, not the model's text.
- Null, empty, non-string, oversized or ungrounded values become `MISSING`. Nothing is invented, and `INVALID`/`EXPLICIT_NULL` are not produced by this extractor.
- Field confidence is `None`; model output carries no calibrated confidence.

## Local OpenAI-compatible provider

`adapters/openai_compatible.py` — `OpenAICompatibleInvoker` for a loopback chat-completions endpoint (for example LM Studio or Ollama).

- Loopback IP literals only, therefore `ExecutionClass.LOCAL_MODEL` with `DataEgress.NONE`.
- `temperature = 0`, strict JSON schema response, and `reasoning_effort = "none"` by default: extraction is a copy task, and reasoning modes added latency and exhausted token budgets in local measurement.
- The API key is read from a named environment variable at call time. It is never in the invocation request, result or document content.
- Non-200 responses, incomplete generations and oversized responses fail; the invocation boundary maps them to stable codes.

## Measured basis

A local benchmark on 30 private business documents (18 used while writing rules/prompts, 12 held out) with PaddleOCR text:

| Approach | Tuning | Held-out |
|---|---|---|
| Heading rules (no match → UNKNOWN) | 17/18 | 12/12 |
| LLM classification, best of five local models per column | 17/18 | 10/12 |

The LLMs repeatedly labelled out-of-scope documents as payment documents, so classification stays deterministic and the model is limited to extraction. With `google/gemma-4-e2b`, about 96–98% of emitted values were grounded in the PDF text layer at about 2 s per document. These figures are sample-specific and do not replace calibration on the deployment's own documents.

## Security

Document text is untrusted model input and is labelled as such in the system instruction. Neither component interprets document text as instructions, routing, schema or authorization. Classification and extracted fields remain predictions and claims, never business authorization.

## Benchmark page

`scripts/benchmark_panel.py` is a local operator page for repeating the measurement on your own samples. It runs the same components (PaddleOCR adapter, `TitleRuleClassifier`, `LlmFieldExtractor`, `OpenAICompatibleInvoker`) and needs the PaddleOCR runtime interpreter:

```powershell
.\.edi\runtimes\paddle-ocr\cpu\venv-win\Scripts\python.exe scripts\benchmark_panel.py --env-file <path-to-.env>
# open http://127.0.0.1:8765/
```

- Choose a folder, select documents and optionally label the expected type (`UNKNOWN` for out-of-scope documents).
- Choose LM Studio models and a classification mode: rules only, rules then LLM, or LLM only. Models are loaded one at a time through the `lms` CLI.
- Per model it reports classification accuracy, abstentions (`UNKNOWN`), wrong non-abstaining labels, `PRESENT` fields, model values rejected as ungrounded, an independent check of `PRESENT` values against the PDF text layer, and LLM latency. A per-document view lists label, prediction, its source and timings. Field values are not shown.
- The page binds `127.0.0.1` and rejects foreign `Host` headers. OCR caches, labels and run results are written to `.edi/bench/` (git-ignored). The API key is read from an environment variable or `--env-file` and is never stored in results.
