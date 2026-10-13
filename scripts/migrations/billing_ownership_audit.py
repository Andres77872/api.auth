#!/usr/bin/env python3
"""Read-only billing ownership report; never repairs or prints provider evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.migrations.billing_provider_bootstrap import _connect, _load_env_file


CHECKS = {
    "paid_entitlements_without_subscription": """
        SELECT id FROM billing_entitlements_current
        WHERE plan_code <> 'free' AND (customer_id IS NULL OR subscription_id IS NULL)""",
    "customers_without_group_access_or_checkout": """
        SELECT bc.id FROM billing_customers bc
        WHERE NOT EXISTS (SELECT 1 FROM v_user_billing_group_access a
                          WHERE a.user_id = bc.user_id AND a.billing_group_id = bc.billing_group_id
                            AND a.billing_group_provider = bc.provider)
          AND NOT EXISTS (SELECT 1 FROM billing_checkout_intents ci
                          WHERE ci.user_id = bc.user_id AND ci.billing_group_id = bc.billing_group_id
                            AND ci.provider = bc.provider)""",
    "subscription_customer_conflicts": """
        SELECT bs.id FROM billing_subscriptions bs
        WHERE NOT EXISTS (SELECT 1 FROM billing_customers bc WHERE bc.id = bs.customer_id
                          AND bc.user_id = bs.user_id AND bc.billing_group_id = bs.billing_group_id
                          AND bc.provider = bs.provider)""",
    "entitlement_reference_conflicts": """
        SELECT ec.id FROM billing_entitlements_current ec
        WHERE (ec.customer_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM billing_customers bc WHERE bc.id = ec.customer_id
              AND bc.user_id = ec.user_id AND bc.billing_group_id = ec.billing_group_id AND bc.provider = ec.provider))
           OR (ec.subscription_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM billing_subscriptions bs WHERE bs.id = ec.subscription_id
              AND bs.user_id = ec.user_id AND bs.billing_group_id = ec.billing_group_id
              AND bs.provider = ec.provider AND bs.customer_id <=> ec.customer_id))""",
    "purchase_customer_conflicts": """
        SELECT pe.id FROM billing_purchase_events pe
        WHERE pe.customer_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM billing_customers bc WHERE bc.id = pe.customer_id
              AND bc.user_id = pe.user_id AND bc.billing_group_id = pe.billing_group_id AND bc.provider = pe.provider)""",
    "purchase_checkout_conflicts": """
        SELECT pe.id FROM billing_purchase_events pe
        WHERE EXISTS (SELECT 1 FROM billing_checkout_intents ci
            WHERE (ci.checkout_ref = pe.checkout_ref OR ci.purchase_ref = pe.purchase_ref)
              AND (ci.user_id <> pe.user_id OR ci.project_id <> pe.project_id
                   OR ci.billing_group_id <> pe.billing_group_id OR ci.provider <> pe.provider
                   OR ci.intent_type <> 'credit_purchase' OR NOT (ci.purchase_ref <=> pe.purchase_ref)
                   OR (pe.checkout_ref IS NOT NULL AND ci.checkout_ref <> pe.checkout_ref)))""",
    "purchases_without_current_or_original_group": """
        SELECT pe.id FROM billing_purchase_events pe
        WHERE NOT EXISTS (SELECT 1 FROM billing_group_projects gp
                          WHERE gp.project_id = pe.project_id AND gp.billing_group_id = pe.billing_group_id AND gp.status = 'active')
          AND NOT EXISTS (SELECT 1 FROM billing_checkout_intents ci
            WHERE (ci.checkout_ref = pe.checkout_ref OR ci.purchase_ref = pe.purchase_ref)
              AND ci.user_id = pe.user_id AND ci.project_id = pe.project_id
              AND ci.billing_group_id = pe.billing_group_id AND ci.provider = pe.provider
              AND ci.intent_type = 'credit_purchase' AND ci.purchase_ref = pe.purchase_ref)""",
    "purchases_without_checkout_evidence": """
        SELECT pe.id FROM billing_purchase_events pe
        WHERE NOT EXISTS (SELECT 1 FROM billing_checkout_intents ci
                          WHERE ci.checkout_ref = pe.checkout_ref OR ci.purchase_ref = pe.purchase_ref)""",
}


def audit(connection, *, limit=20):
    report = {"read_only": True, "checks": {}}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            for name, query in CHECKS.items():
                cursor.execute(f"SELECT COUNT(*) AS total FROM ({query}) findings")
                total = int(cursor.fetchone()["total"])
                cursor.execute(query + " ORDER BY id LIMIT %s", (limit,))
                report["checks"][name] = {"count": total, "sample_local_ids": [row["id"] for row in cursor.fetchall()]}
    finally:
        connection.rollback()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Explicit database environment file")
    parser.add_argument("--limit", type=int, default=20, help="Maximum local record ids per check")
    args = parser.parse_args(argv)
    if not 0 <= args.limit <= 1000:
        parser.error("--limit must be between 0 and 1000")
    _load_env_file(args.env_file)
    connection = None
    try:
        connection = _connect()
        print(json.dumps(audit(connection, limit=args.limit), indent=2))
        return 0
    except Exception as exc:
        # Connection exceptions can contain credentials/hosts; print only their class.
        print(f"Billing ownership audit unavailable: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
