# Control panel operations

Design and security model: [`docs/RI-4.11-CONTROL-PANEL.md`](../RI-4.11-CONTROL-PANEL.md).

## Prerequisites

- Repository installed (`pip install -e .`), PaddleOCR runtime installed (`edi install --provider paddle-ocr --profile cpu --yes`), OCR model directories available.
- LM Studio with its `lms` CLI for LLM extraction (optional; rules-only processing works without it).

## 1. Create the first admin

```powershell
edi panel-user add admin --role ADMIN
# prompts twice for a password of at least 12 characters
edi panel-user add operator1 --role OPERATOR
edi panel-user list
```

Other actions: `passwd`, `role --role VIEWER|OPERATOR|ADMIN`, `disable`, `enable`. Users can also be managed in the panel (Audit & Pengguna tab).

## 2. Local use (this PC only)

```powershell
edi serve-panel --env-file F:\path\to\.env
# open http://127.0.0.1:8443/
```

## 3. Office network (LAN)

A certificate and key are required. For a small office, a self-signed certificate is acceptable when users trust it once; an internal CA is better.

```powershell
# Git for Windows ships OpenSSL. Replace 192.168.1.20 / panel.lan with the PC's address and name.
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -keyout panel.key -out panel.crt `
  -subj "/CN=panel.lan" -addext "subjectAltName=DNS:panel.lan,IP:192.168.1.20"

edi serve-panel --bind 0.0.0.0 --port 8443 --tls-cert panel.crt --tls-key panel.key `
  --allowed-host 192.168.1.20:8443 --allowed-host panel.lan:8443 --env-file F:\path\to\.env
```

Allow the port only on private networks:

```powershell
New-NetFirewallRule -DisplayName "EDI control panel" -Direction Inbound -Protocol TCP -LocalPort 8443 -Profile Private -Action Allow
```

Clients open `https://192.168.1.20:8443/`. Every address or name clients type must be passed as `--allowed-host`, otherwise requests are rejected with `HOST_NOT_ALLOWED`.

## Options

| Option | Default | Purpose |
|---|---|---|
| `--state-dir` | `.edi/panel` | users, audit log, configuration, documents, results |
| `--ocr-python` | runtime `paddle-ocr/cpu` interpreter | isolated PaddleOCR interpreter |
| `--ocr-det-*`, `--ocr-rec-*` | `.edi/models/paddle-ocr/legacy-en/…` | initial OCR models (later changed under Konfigurasi) |
| `--title-rules` | `deploy/classification-profiles/title-rules-id-en.json` | initial title-rule profile |
| `--lms`, `--llm-port` | `~/.lmstudio/bin/lms`, `12340` | LM Studio control and endpoint |
| `--api-key-env`, `--env-file` | `LM_STUDIO_API_KEY` | where the local model server key is read from |

## Routine checks

- **Ringkasan:** LM Studio running, model loaded, OCR runtime present, OCR models "terverifikasi" (pinned). Use "Pin digest model OCR" under Konfigurasi after installing or changing OCR models.
- **Audit & Pengguna:** "Rantai hash utuh" must be shown; a broken chain means the audit file was edited.
- Back up `--state-dir` regularly; it holds documents and results.
