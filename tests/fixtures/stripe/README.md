# Stripe test fixtures

Synthetic fixture set for SDD change `provider-agnostic-billing-stripe`, Phase 1.

- All provider IDs, user/project hashes, timestamps, amounts, URLs, and signatures are fake.
- Do not paste live Stripe Dashboard payloads, real Stripe CLI captures, API keys, webhook secrets, card data, payment-method data, receipt URLs, or customer PII into this tree.
- Webhook payload files under `webhooks/*.json` are byte-exact raw request bodies for later signature tests. Read them as bytes; do not parse and re-serialize before verification.
- Fixture signatures in `webhooks/signature_headers.json` use the synthetic endpoint secret `whsec_test_stripe_fixture_secret_do_not_use` and Stripe's `t=<timestamp>,v1=<hmac>` header shape.
- Signatures are computed over `{timestamp}.{exact raw fixture bytes}` including the final LF byte.
- Tests that enforce the timestamp tolerance must freeze time to the fixture timestamp or explicitly pass the documented tolerance window. The default tolerance is 300 seconds.
- `tampered_body.json` intentionally pairs changed body bytes with the signature for `checkout_session_completed_subscription.json`; verification must fail because Stripe signs exact raw bytes.
- Body normalization must fail verification: whitespace changes, key reordering, Unicode normalization, or JSON parse/dump round-trips change the signed bytes even if the semantic JSON looks equivalent.
- `malformed_payload.json` is intentionally invalid JSON and exists to prove invalid provider payload handling without requiring real Stripe traffic.

Canonical layout:

- `webhooks/manifest.json` — stable fixture index for tests.
- `webhooks/*.json` — exact synthetic raw webhook request bodies and negative controls.
- `webhooks/signature_headers.json` — expected `Stripe-Signature` headers, SHA-256 body hashes, byte lengths, and verification expectations.
