"""Pure rules for a task's two long-form, versioned text fields — the
Description (written by the user or the agent as the task gets clearer) and
the Execution Summary (written by the agent once it finishes, fails, or
parks the task). No I/O lives here; `services.task_fields_service` owns the
storage and compare-and-swap.

Both fields share one revision mechanism, so everything about a field's
storage keys is derived from its single `FieldSpec` rather than repeated.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class FieldSpec:
    key: str   # the name used in URLs, the revisions collection and the API
    attr: str  # the task-document key holding the current content

    def version_key(self) -> str:
        return f"{self.attr}Version"

    def updated_at_key(self) -> str:
        return f"{self.attr}UpdatedAt"

    def updated_by_key(self) -> str:
        return f"{self.attr}UpdatedBy"

    def status_key(self) -> str:
        return f"{self.attr}Status"


DESCRIPTION = FieldSpec(key="description", attr="description")
SUMMARY = FieldSpec(key="summary", attr="completionSummary")

FIELDS = {f.key: f for f in (DESCRIPTION, SUMMARY)}

MAX_CONTENT_CHARS = 50_000
AUTHOR_TYPES = ("human", "agent", "integration")
# What a summary's status label can be — the terminal/parked task statuses.
SUMMARY_STATUSES = ("done", "failed", "manual", "stopped", "blocked")


def get_field_spec(key: str) -> Optional[FieldSpec]:
    return FIELDS.get(key)


def _meaningful_lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def removed_lines(old: str, new: str) -> List[str]:
    """Non-blank lines present in `old` that no longer appear anywhere in
    `new`. Line-level on purpose: cheap, deterministic, and good enough to
    tell "the agent dropped something" from "the agent only added to it"."""
    kept = set(_meaningful_lines(new))
    return [ln for ln in _meaningful_lines(old) if ln not in kept]


def append_revision_note(content: str, removed_summary: str) -> str:
    """Appends the agent's own acknowledgement of what its overwrite
    removed, so the loss is visible in the text itself and not only in the
    history popover."""
    return f"{content.rstrip()}\n\n---\n**Revision note (agent):** removed — {removed_summary.strip()}\n"
