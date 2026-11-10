# Implementation Plan: External Messaging & Notification Subsystem

**Branch:** `external-messaging-support`  
**Parent Target:** `main`  
**Specification Reference:** [`docs/specs/SPEC_EXTERNAL_MESSAGING.md`](../specs/SPEC_EXTERNAL_MESSAGING.md)  
**Status:** In Progress (Planning & Spec Phase)

---

## 1. Objectives & Scope

Deliver an out-of-the-box, zero-dependency external notification system allowing ULTRON PRIME and Hive teams to message the user via **Email**, **Telegram**, **WhatsApp**, **Viber**, **ntfy.sh**, and **Webhooks (Discord/Slack)** on mobile and desktop.

### Success Invariants:
1. **Zero External Dependencies:** Uses only Python standard library (`smtplib`, `urllib.request`, `ssl`, `json`, `email`).
2. **Fail-Loud & Observable:** Never swallows errors or uses fake mocks in live runs; emits explicit failure diagnostics.
3. **Secret Safety:** Credentials live strictly in `.runtime/notifications.json` (gitignored) or environment variables; sanitized `.example.json` tracked in Git.
4. **Comprehensive Test Suite:** 100% test pass rate with mocked networking fixtures verifying all 6 providers.

---

## 2. Phased Execution Roadmap

### Phase 1: Core Engine & Configuration Skeleton
- [ ] Create `ultron/core/templates/notifications.example.json` containing documented schema for all channels.
- [ ] Create `ultron/core/notifier.py` with:
  * `NotificationResult` dataclass.
  * `BaseNotificationProvider` abstract class.
  * `NotificationManager` for loading configuration, resolving providers, managing rate-limits, and handling dispatch.
  * Secret masking utility for safe CLI display.

### Phase 2: Channel Provider Implementations (`ultron/core/notifier.py`)
- [ ] **Email Provider (`EmailProvider`):**
  * SMTP / STARTTLS / SSL support via `smtplib`.
  * Multipart MIME HTML + plain-text fallback generator.
  * Severity-based subject and header theming.
- [ ] **Telegram Provider (`TelegramProvider`):**
  * Telegram Bot API POST requests using `urllib.request`.
  * HTML entity escaping and message formatting.
- [ ] **WhatsApp Provider (`WhatsAppProvider`):**
  * CallMeBot GET transport for personal WhatsApp alerts.
  * Meta Cloud API POST transport for business accounts.
- [ ] **Viber Provider (`ViberProvider`):**
  * Viber Chat REST API POST with auth headers and receiver validation.
- [ ] **ntfy.sh Provider (`NtfyProvider`):**
  * Instant mobile push notification dispatch with custom topics, priority, and click links.
- [ ] **Webhook Provider (`WebhookProvider`):**
  * Discord embed formatter, Slack blocks formatter, and generic JSON webhook.

### Phase 3: ULTRON Core CLI Integration (`ultron/core/core.py`)
- [ ] Register CLI subcommands in `build_parser()`:
  * `notify <message> [--title <title>] [--channel <channel>] [--severity <sev>] [--json]`
  * `notify-test [--channel <channel>] [--json]`
  * `notify-config [--show-secrets] [--json]`
  * `notify-enable <channel>` / `notify-disable <channel>`
- [ ] Add `UltronCore.notify()` API method.
- [ ] Bind CLI command handlers in `main()`.

### Phase 4: Lifecycle Hooks & Message Board Integration
- [ ] Add helper to trigger notifications automatically on key thread events:
  * Thread marked `resolved` $\rightarrow$ dispatch summary notification with report link.
  * Thread created or replied with `#gate` / `gate` category $\rightarrow$ dispatch human sign-off request.
  * Thread marked `#blocker` or critical deadlock $\rightarrow$ dispatch emergency alert.

### Phase 5: Rigorous Automated Testing (`tests/test_notifications.py`)
- [ ] Author test suite with mock transports (intercepting `smtplib.SMTP` and `urllib.request.urlopen`):
  * Test configuration loading, validation, and secret masking.
  * Test email provider HTML generation and SMTP dispatch.
  * Test Telegram provider payload and response handling.
  * Test WhatsApp CallMeBot & Cloud API requests.
  * Test Viber provider headers and payload structure.
  * Test ntfy.sh headers and priorities.
  * Test Webhook provider (Discord/Slack formatting).
  * Test CLI subcommands (`notify`, `notify-test`, `notify-config`, etc.).
  * Test error conditions (network failure, HTTP 401, SMTP auth error, malformed config).

### Phase 6: Documentation, Review & Final Verification
- [ ] Update `README.md` and `ultron/core/README.md` with notification guides and quickstarts.
- [ ] Update `docs/ARCHITECTURE.md` to reflect the new Notifier Subsystem.
- [ ] Run full test suite: `python3 -W error -m unittest discover -s tests -v`.
- [ ] Verify repository integrity: `python3 ultron/core/core.py verify`.
- [ ] Review git diff, commit to `external-messaging-support`, and push branch to GitHub.

---

## 3. Risk Assessment & Mitigations

| Risk | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **Accidental secret leak in git** | High | Config file strictly placed in `.runtime/notifications.json` (gitignored). Template committed as `.example.json`. CLI masks tokens by default. |
| **External dependency bloat** | Medium | Strictly zero 3rd-party dependencies. All HTTP/SMTP calls implemented via Python stdlib. |
| **Network hang / slow remote servers** | Medium | Explicit socket timeouts (`timeout=10`) on all network connections to prevent hanging autonomous agents. |
| **Notification flood / spam** | Medium | Built-in client-side debounce / rate-limiting in `NotificationManager`. |