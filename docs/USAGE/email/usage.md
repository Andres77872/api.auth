# Email Templates — Usage

Task-oriented walkthroughs for the ROOT-only transactional email template API (`/admin/email-templates`) and for wiring the inbound Resend webhook. For the full endpoint table and config keys see [reference.md](reference.md); for how a sent message actually ships see [architecture.md](architecture.md).

> All `/admin/email-templates` calls are **ROOT only** and use **JSON** bodies (not form data). Every request needs a `User-Agent` header. Examples below use a bearer token; a session cookie works the same way.

```bash
BASE_URL="https://auth.example.com"
TOKEN="<root session bearer token>"
```

---

## 1. List and inspect a template (with version history)

List every transactional template and its active source/version:

```bash
curl -X GET "${BASE_URL}/admin/email-templates" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "User-Agent: ops/1.0"
```

Each entry reports `source` (`code` = built-in default, `db` = customized), `version` (a number when DB-managed, `null` for the in-code default), `required_variables`, and the `allowed_variables` allowlist.

Inspect one code — active body, the built-in `default` body, the allowlist, and full `versions[]` history:

```bash
curl -X GET "${BASE_URL}/admin/email-templates/email_activation" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "User-Agent: ops/1.0"
```

An unknown code returns `404 RESOURCE_NOT_FOUND`. The five valid codes are `email_activation`, `password_reset`, `admin_password_reset`, `security_notification`, and `delivery_operation`.

---

## 2. Edit a template safely (PUT creates a new active version)

`PUT` runs the full draft validation pipeline (`validate_template_draft`) before anything is saved:

- every `$placeholder` must be in the per-code allowlist;
- every required variable for the code must be present;
- the HTML must pass the safety check;
- a render smoke test must succeed.

```bash
curl -X PUT "${BASE_URL}/admin/email-templates/email_activation" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/json" \
  -d '{
        "subject_template": "Activate your $app_name email",
        "html_template": "<!DOCTYPE html><html><body><p>Activate $recipient_masked</p><a href=\"$activation_link\">Activate</a><p>Expires in $expires_in.</p></body></html>",
        "text_template": "Activate $recipient_masked for $app_name:\n$activation_link\nExpires in $expires_in."
      }'
```

On success the response returns the **new** `version` and the `used_variables` the validator detected:

```json
{ "success": true, "template_code": "email_activation", "version": 5, "used_variables": ["app_name", "recipient_masked", "activation_link", "expires_in"], "updated_at": "2026-06-14T12:00:00Z" }
```

A validation failure returns `400 INVALID_INPUT` and **does not** save a version. Use `$name` / `${name}` placeholders only — templates render with `string.Template`, not `str.format`, and a stray `$` is itself rejected.

> Placeholders are limited to each code's allowlist. For example `email_activation` allows `app_name`, `recipient_masked`, `expires_in`, `support_email`, `activation_link`; `security_notification` allows `app_name`, `support_email`, `event_title`, `message`. See the `allowed_variables` field returned by the GET endpoints.

---

## 3. Preview a draft (sandboxed iframe)

Preview validates and renders a draft using the **server-side** `sample_variables` (you never supply variable values):

```bash
curl -X POST "${BASE_URL}/admin/email-templates/email_activation/preview" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/json" \
  -d '{
        "subject_template": "Activate your $app_name email",
        "html_template": "<!DOCTYPE html>...$activation_link...",
        "text_template": "Activate ...\n$activation_link"
      }'
```

Omit the body (or send `{}`) to preview the **active** version instead of a draft. The response carries `subject`, `html`, `text`, and the `sample_variables` used. The returned `html` is exactly what the worker would send — render it in a **script-less sandboxed iframe**; do not execute it.

---

## 4. Send a test to your own verified address

`send-test` renders the template and sends a `[TEST]`-prefixed message. Three guarantees:

- **Recipient is locked** to *your own* activated email (the first `status == "activated"` address on the ROOT caller's account). There is **no** recipient field — you cannot send to an arbitrary address.
- **Delivery must be ready** (`validate_email_readiness` ⇒ `ready`). If delivery is disabled or config is incomplete, you get `400` with `Email delivery is not ready (status: ...)`.
- **Rate-limited** under `purpose="email_template_test"` (recipient 3/hr & 10/day, user 5/hr, IP 20/hr by default).

```bash
curl -X POST "${BASE_URL}/admin/email-templates/email_activation/send-test" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{ "success": true, "template_code": "email_activation", "recipient_masked": "j***@example.com", "provider": "resend", "sent_at": "2026-06-14T12:00:00Z" }
```

Like preview, you may include draft fields in the body to test an unsaved draft. The response only ever returns the **masked** recipient; the audit log redacts the address entirely. If you have no activated email on file, you get `400 INVALID_INPUT` (`You have no verified email address on file ...`).

---

## 5. Roll back to a prior version

Re-activate an earlier version by number (find versions via the GET-by-code `versions[]` list):

```bash
curl -X POST "${BASE_URL}/admin/email-templates/email_activation/rollback" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/json" \
  -d '{ "version": 3 }'
```

```json
{ "success": true, "template_code": "email_activation", "version": 3, "rolled_back_at": "2026-06-14T12:00:00Z" }
```

A `version` that does not exist for the code returns `404 RESOURCE_NOT_FOUND`. Rollback re-activates the stored version as the active one; it does not delete the version you rolled away from.

---

## 6. Configure and verify a Resend webhook endpoint

Point your Resend/Svix webhook at:

```text
POST https://auth.example.com/webhooks/email/resend
```

The endpoint takes **no application auth**; it is authenticated by the Svix signature over the raw request body. Requirements:

1. Set `RESEND_WEBHOOK_SECRET` to the Svix signing secret from the Resend dashboard.
2. Resend must send the `svix-id`, `svix-timestamp`, and `svix-signature` headers (it does by default).
3. Subscribe to delivery/bounce/complaint events (`email.delivered`, `email.sent`, `email.bounced`, `email.complained`).

Verify behavior:

- A valid signed event returns **`204 No Content`** and updates delivery/suppression state.
- A missing header or bad signature returns **`400 "Invalid webhook signature"`** and mutates nothing.
- Unsupported event types are accepted and ignored, also returning `204`.

> Do **not** put a body-rewriting proxy in front of this endpoint. Svix verifies the **raw bytes**; reserializing the JSON breaks the signature.

For secret rotation and bounce/complaint operations, see the [Email Activation Runbook](../../RUNBOOKS/email-activation.md).

---

## Related flows handled elsewhere

- A user's email addresses (add/list/activate/resend/remove) → [Users Documentation](../users/README.md).
- Reading sanitized email delivery logs (`GET /admin/email/logs`) → [Audit Logs Usage Cases](../audit-log-usage-cases.md).
- Public verify/forgot/reset link consumption (`/auth/...`) → [Authentication Usage Cases](../authentication-usage-cases.md).

---

**Last Updated**: June 2026
**Document Version**: 1.0
