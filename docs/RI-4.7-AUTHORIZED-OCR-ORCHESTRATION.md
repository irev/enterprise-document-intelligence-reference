# RI-4.7 — Authorized OCR Orchestration

The reference implementation now has one application-level path for OCR text extraction.

execute_ocr_text_extraction performs provider-neutral planning for TEXT_EXTRACTION, resolves the selected registered provider and invoker, and executes through invoke_planned_provider. Current control-plane authorization is therefore evaluated immediately before provider code is called.

The orchestration does not select PaddleOCR directly. A local OCR adapter, another local engine, or another policy-eligible provider can be registered without changing this application flow.

The current scope returns InvocationResult. Structured OCR geometry and canonical document construction remain separate boundaries until the provider invocation contract can transport structured output without encoding provider-specific DTOs.

This implementation exercises the blueprint invariant established by ADR-0011: an execution plan records selection but does not grant provider authorization.
