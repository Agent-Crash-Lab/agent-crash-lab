"""Explicit simulator registrations. A caller-provided name cannot register code."""

from harness.adapters.manufacturing import load_adapters
from harness.adapters.reference_purchase import ReferencePurchaseAdapter


def registered_adapters(root, config):
    reference = ReferencePurchaseAdapter(root, config)
    return {a.adapter_id: a for a in [reference, *load_adapters(root)]}
