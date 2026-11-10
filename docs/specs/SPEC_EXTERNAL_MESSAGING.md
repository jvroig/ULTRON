# Technical Specification: ULTRON External Messaging & Notification Subsystem

**Document Version:** 1.0.0  
**Status:** Approved for Implementation  
**Branch:** `external-messaging-support`  
**Target Subsystem:** `ultron/core/` (`notifier.py`, `core.py`, CLI)

---

## 1. Executive Summary & Purpose

ULTRON is an autonomous multi-agent engineering network capable of long-running workflows: overnight feature generation, deep architecture audits, safety heartbeats, and continuous test verification. Currently, agents coordinate via append-only JSONL message boards and reactive subagent doorbells.

However, human operators cannot and should not be expected to constantly monitor the browser or CLI terminal. 

The **External Messaging & Notification Subsystem** provides an out-of-the-box, zero-mandatory-dependency bridge between ULTRON and the user's primary communication channels—delivering actionable phone push notifications, milestone reports, critical gate alerts, and blocker warnings to:
1. **Email** (SMTP with HTML and Markdown formatting via Python standard library)
2. **Telegram** (Instant mobile push notifications & rich Markdown via Telegram Bot API)
3. **WhatsApp** (Personal alerts via CallMeBot gateway and business alerts via Meta Cloud API)
4. **Viber** (Direct 1-on-1 bot messaging via Viber REST Chat API)
5. **ntfy.sh** (Zero-signup, open-source instant mobile push alerts)
6. **Generic Webhooks** (Slack, Discord, and custom automation endpoints)

---

## 2. Core Architectural Principles

1. **Zero Mandatory External Dependencies:**
   - All core providers (Email, Telegram, WhatsApp CallMeBot, Viber, ntfy.sh, Webhooks) must operate strictly using Python 3.10+ standard libraries (`urllib.request`, `urllib.parse`, `smtplib`, `ssl`, `email.message`, `json`, `pathlib`).
   - No `pip install` required for basic or advanced notification dispatch.

2. **Pluggable Multi-Channel Provider Model:**
   - Unified `NotificationProvider` abstraction with uniform interfaces: `send()`, `test()`, and `validate_config()`.
   - Ability to dispatch to single channels (`--channel telegram`) or broadcast to all active channels simultaneously.

3. **Strict Credential & Secret Hygiene:**
   - Secrets (bot tokens, SMTP passwords, API keys) must **never** be committed to Git.
   - Primary credentials loaded from `.runtime/notifications.json` (gitignored).
   - Sanitized template tracked in repository: `ultron/core/templates/notifications.example.json`.
   - Transparent environment variable fallback (`ULTRON_NOTIFY_EMAIL_PASS`, `ULTRON_NOTIFY_TELEGRAM_TOKEN`, etc.) for containerized and headless environments.

4. **Fail-Loud & Diagnostic Transparency (Zero Silent Mock Fallbacks):**
   - If a configured channel encounters a network timeout, authentication rejection, or malformed payload, report the exact error code and diagnostic body.
   - Do not pretend messages succeeded when services are offline or misconfigured.
   - A partial broadcast failure (e.g., Telegram succeeds but SMTP server times out) must report per-channel status breakdown with non-zero exit code if requested channels failed.

---

## 3. Configuration & Schema Contract

### 3.1 Configuration File Location & Precedence
1. Explicit CLI flag: `--config <path>`
2. Repository Runtime Path: `ultron/core/.runtime/notifications.json`
3. Environment Variables (override config values at runtime)

### 3.2 Configuration JSON Schema (`notifications.json`)
```json
{
  "active_channels": ["telegram", "email"],
  "rate_limit_seconds": 2,
  "channels": {
    "email": {
      "enabled": true,
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "use_tls": true,
      "username": "user@example.com",
      "password": "app-password-here",
      "from_address": "ULTRON PRIME <user@example.com>",
      "to_addresses": ["user@example.com"],
      "subject_prefix": "[ULTRON]"
    },
    "telegram": {
      "enabled": true,
      "bot_token": "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ",
      "chat_id": "987654321",
      "parse_mode": "HTML"
    },
    "whatsapp": {
      "enabled": false,
      "mode": "callmebot",
      "callmebot": {
        "phone": "+1234567890",
        "api_key": "123456"
      },
      "cloud_api": {
        "phone_number_id": "",
        "access_token": "",
        "recipient_phone": "",
        "template_name": "ultron_alert"
      }
    },
    "viber": {
      "enabled": false,
      "auth_token": "your-viber-auth-token",
      "receiver_id": "viber-user-hash-id",
      "sender_name": "ULTRON PRIME"
    },
    "ntfy": {
      "enabled": false,
      "server_url": "https://ntfy.sh",
      "topic": "ultron-notifications-demo",
      "priority": "high",
      "access_token": ""
    },
    "webhook": {
      "enabled": false,
      "url": "https://discord.com/api/webhooks/...",
      "format": "discord"
    }
  }
}
```

---

## 4. Provider Specifications

### 4.1 Base Provider Interface (`ultron/core/notifier.py`)
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class NotificationResult:
    channel: str
    success: bool
    status_code: Optional[int] = None
    message_id: Optional[str] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class BaseNotificationProvider(ABC):
    name: str

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def validate_config(self) -> List[str]:
        """Returns list of missing/invalid configuration field errors."""
        pass

    @abstractmethod
    def send(
        self,
        message: str,
        title: Optional[str] = None,
        severity: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NotificationResult:
        """Sends notification to recipient."""
        pass

    def test(self) -> NotificationResult:
        """Sends a verification probe test message."""
        return self.send(
            message="This is a test notification from ULTRON.",
            title="ULTRON Connection Test",
            severity="info",
        )
```

### 4.2 Email Provider (`EmailProvider`)
* **Transport:** `smtplib.SMTP` (STARTTLS, port 587) or `smtplib.SMTP_SSL` (port 465).
* **Payload:** Multipart MIME (`email.message.EmailMessage`) with plain text fallback and rich HTML layout.
* **Features:**
  - Severity styling (Info = Blue, Warning = Amber, Critical = Crimson).
  - Optional attachment support (diff patches, test logs, JSONL export files).
  - Subject format: `[{prefix}] [{severity.upper()}] {title}`.

### 4.3 Telegram Provider (`TelegramProvider`)
* **Endpoint:** `https://api.telegram.org/bot{token}/sendMessage`
* **Transport:** Standard `urllib.request.urlopen` over HTTPS.
* **Payload:** JSON with `chat_id`, `text`, `parse_mode` (`HTML` or `MarkdownV2`), and `disable_web_page_preview`.
* **Formatting:** Automatically escapes HTML entities (`&`, `<`, `>`) in message bodies while wrapping headers and severity badges.
* **Interactive Extensions (Level 2 Ready):** Supports `reply_markup` for `inline_keyboard` approval buttons.

### 4.4 WhatsApp Provider (`WhatsAppProvider`)
* **Mode 1 — CallMeBot (Default Personal):**
  - Endpoint: `https://api.callmebot.com/whatsapp.php?phone={phone}&text={text}&apikey={api_key}`
  - Transport: `urllib.request.urlopen` GET request.
  - Formatting: WhatsApp Markdown (`*bold*`, `_italics_`, `~strike~`, ```code```).
* **Mode 2 — Meta Cloud API (Official):**
  - Endpoint: `https://graph.facebook.com/v19.0/{phone_number_id}/messages`
  - Transport: POST JSON with `Authorization: Bearer {access_token}`.
  - Template or freeform text payload.

### 4.5 Viber Provider (`ViberProvider`)
* **Endpoint:** `https://chatapi.viber.com/pa/send_message`
* **Transport:** POST JSON with `X-Viber-Auth-Token` header.
* **Payload:**
  ```json
  {
    "receiver": "...",
    "min_api_version": 1,
    "sender": {"name": "ULTRON PRIME"},
    "type": "text",
    "text": "..."
  }
  ```
* **Validation:** Checks for receiver hash token and auth token existence.

### 4.6 ntfy.sh Provider (`NtfyProvider`)
* **Endpoint:** `{server_url}/{topic}`
* **Transport:** POST request with string body and HTTP header metadata.
* **Headers:** `Title`, `Priority` (`min`, `low`, `default`, `high`, `urgent`), `Tags` (`warning`, `robot`, etc.), `Click` (URL to thread/repo).

### 4.7 Webhook Provider (`WebhookProvider`)
* **Transport:** Generic POST JSON.
* **Presets:**
  - `discord`: Embed object with colors and field blocks.
  - `slack`: Slack blocks / attachment payload.
  - `generic`: Clean standard JSON payload (`{"title": "...", "message": "...", "severity": "...", "timestamp": "..."}`).

---

## 5. CLI Interface & Commands

The following subcommands will be exposed directly via `python3 ultron/core/core.py`:

### 5.1 `notify`
Sends a message to the user across configured channels.
```bash
python3 ultron/core/core.py notify <message> \
  [--title <title>] \
  [--channel {all,email,telegram,whatsapp,viber,ntfy,webhook}] \
  [--severity {info,warning,critical}] \
  [--json]
```

### 5.2 `notify-test`
Probes and verifies connectivity for configured channels.
```bash
python3 ultron/core/core.py notify-test [--channel <channel>] [--json]
```

### 5.3 `notify-config`
Displays current notification configuration status (with sensitive secrets safely masked by default).
```bash
python3 ultron/core/core.py notify-config [--show-secrets] [--json]
```

### 5.4 `notify-enable` & `notify-disable`
Quickly activates or deactivates individual channels in `.runtime/notifications.json`.
```bash
python3 ultron/core/core.py notify-enable telegram
python3 ultron/core/core.py notify-disable email
```

---

## 6. Integration with ULTRON Lifecycle & Message Board

The notification engine integrates with existing ULTRON workflows in three distinct scenarios:

1. **Mission Completion / Sign-Off:**
   When a Team Lead or ULTRON PRIME transitions a thread to `RESOLVED` (e.g., `set-status <id> resolved`), dispatch an informational summary notification with link to the exported Markdown report.

2. **Gated Human Approvals (`#gate`):**
   When an autonomous team completes a major milestone and requires human sign-off before proceeding (e.g., deployment, production migration, or public PR creation), dispatch a high-priority notification with instructions.

3. **Critical Blockers & Safety Cron Deadlocks (`#blocker`, `CRITICAL`):**
   When the recurring safety cron detects a process crash, timeout, or stalled handoff that cannot be resolved automatically, dispatch a critical alert to the operator's phone.

---

## 7. Acceptance Criteria (AC-1 through AC-10)

* **AC-1:** Zero mandatory third-party pip dependencies. All providers must compile and run using standard Python 3.10+ libraries.
* **AC-2:** Multi-channel provider registry with clean pluggable abstraction (`BaseNotificationProvider`, `NotificationResult`).
* **AC-3:** Configuration file loader with strict validation, `.runtime/notifications.json` location, `.example.json` tracking, and environment variable overrides.
* **AC-4:** Email provider supporting SMTP/TLS, HTML rendering with plain-text fallback, and severity headers.
* **AC-5:** Telegram provider supporting Telegram Bot API HTTPS POST, HTML entity escaping, and Markdown/HTML formatting.
* **AC-6:** WhatsApp provider supporting CallMeBot GET endpoint and Meta Cloud API POST endpoint.
* **AC-7:** Viber provider supporting Viber Chat REST API POST with auth headers and receiver validation.
* **AC-8:** ntfy.sh and generic Webhook providers supporting priority, title, and action URLs.
* **AC-9:** CLI commands (`notify`, `notify-test`, `notify-config`, `notify-enable`, `notify-disable`) with clear stdout/stderr and `--json` support.
* **AC-10:** Comprehensive automated unit test suite with mock transport layers verifying formatting, error handling, rate limiting, and fail-loud diagnostics.