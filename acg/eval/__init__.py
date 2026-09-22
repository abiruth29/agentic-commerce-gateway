"""The evaluation harness: corpus, configurations, and metrics.

Separate from the gateway on purpose. Nothing in `acg.eval` is imported by the
serving path, so the harness can hold fixtures, a fixed clock and a corpus of
live attack text without any of it becoming reachable from a request.
"""
