"""timeout_watchdog.py — a DISTINCT signal before a Lambda timeout kills the run.

#2669: a Lambda timeout ends with a generic platform REPORT line that is
indistinguishable in our own logs from a run that never got far. wednesday-
chronicle died at its 120s wall three times in 21 days — each time AFTER the
paid model pipeline completed — and the logs could not say so. The watchdog
arms a daemon timer that, ~`margin_s` before the deadline, emits an [ERROR]
line + a CloudWatch metric — while the process can still say anything — so a
timeout is named, alarmable, and separable from every other failure shape.

Usage (in a handler wrapper):

    timer = arm(context, metric_name="ChronicleTimeoutImminent", detail="...")
    try:
        return _handler_core(event, context)
    finally:
        disarm(timer)

Stdlib + lazy boto3; safe to import anywhere (#781 bundle).
"""

import os
import threading

_NAMESPACE = "LifePlatform/Email"
_MARGIN_S = 8.0
# Below this much headroom, arming would fire instantly — a watchdog that cries
# on every short invoke is noise, not signal.
_MIN_HEADROOM_S = 10.0


def arm(context, *, metric_name, detail="", namespace=_NAMESPACE, margin_s=_MARGIN_S):
    """Start the watchdog. Returns the timer (pass to disarm), or None without headroom."""
    remaining = context.get_remaining_time_in_millis() / 1000.0 if context else 0.0
    if remaining <= _MIN_HEADROOM_S:
        return None

    def _imminent():
        print(f"[ERROR] [#2669] timeout imminent (<{margin_s:.0f}s remaining) — {detail}")
        try:
            import boto3

            boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2")).put_metric_data(
                Namespace=namespace,
                MetricData=[{"MetricName": metric_name, "Value": 1.0, "Unit": "Count"}],
            )
        except Exception as e:  # noqa: BLE001 — the log line above already landed
            print(f"[#2669] timeout metric emit failed (non-fatal): {e}")

    timer = threading.Timer(max(remaining - margin_s, 1.0), _imminent)
    timer.daemon = True
    timer.start()
    return timer


def disarm(timer):
    """Cancel a watchdog from arm(). None-safe."""
    if timer is not None:
        timer.cancel()
