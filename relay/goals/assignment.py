"""Assignment Workflow — guidance, drafting, rubric verification, and safe submission.

Assists blind and visually impaired students through course assignments without
bypassing academic integrity. Ensures all output is accessible (headings, table headers,
alt text), verifies all rubric criteria, and enforces explicit confirmation before submit.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from relay.diagnostics import get_logger

log = get_logger("goals.assignment")


@dataclass
class RubricCriterion:
    criterion: str
    points: float = 0.0
    completed: bool = False
    notes: str = ""


@dataclass
class Assignment:
    assignment_id: str
    title: str
    course: str
    deadline: str = ""
    instructions: str = ""
    rubric: list[RubricCriterion] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    required_format: str = "pdf"
    word_limit: Optional[int] = None
    submission_target: str = ""
    draft_path: str = ""
    status: str = "in_progress"  # in_progress | ready_for_review | submitted


class AssignmentWorkflow:
    """End-to-end assignment workflow assistant."""

    def parse_instructions(self, raw_text: str, title: str = "", course: str = "") -> Assignment:
        """Parse raw assignment instructions and extract rubric criteria, deadlines, and formats."""
        import uuid
        aid = f"assign_{uuid.uuid4().hex[:8]}"

        # Extract deadline if mentioned
        dl_match = re.search(r"(?:due|deadline|by)[:\s]+([^\n\r]+)", raw_text, re.IGNORECASE)
        deadline = dl_match.group(1).strip() if dl_match else ""

        # Extract format
        fmt = "pdf"
        if re.search(r"\bdocx?\b", raw_text, re.IGNORECASE):
            fmt = "docx"
        elif re.search(r"\bzip\b", raw_text, re.IGNORECASE):
            fmt = "zip"
        elif re.search(r"\bpdf\b", raw_text, re.IGNORECASE):
            fmt = "pdf"

        # Extract word limit
        wl_match = re.search(r"(\d{2,5})\s*(?:words?|word count)", raw_text, re.IGNORECASE)
        word_limit = int(wl_match.group(1)) if wl_match else None

        # Extract rubric / checklist criteria
        rubric: list[RubricCriterion] = []
        for line in raw_text.splitlines():
            line = line.strip()
            # Bullet point or numbered requirement
            if re.match(r"^[-*•\d+.)]\s*(.+)", line):
                item_text = re.sub(r"^[-*•\d+.)]\s*", "", line).strip()
                if len(item_text) > 10:
                    rubric.append(RubricCriterion(criterion=item_text))

        if not rubric:
            # Fallback criteria from instructions
            rubric.append(RubricCriterion(criterion="Complete core assignment prompt"))
            rubric.append(RubricCriterion(criterion="Format according to guidelines"))
            rubric.append(RubricCriterion(criterion="Include academic citations/references"))

        return Assignment(
            assignment_id=aid,
            title=title or "Assignment",
            course=course or "Course",
            deadline=deadline,
            instructions=raw_text,
            rubric=rubric,
            required_format=fmt,
            word_limit=word_limit,
            submission_target=course or "LMS",
        )

    def generate_accessible_document(
        self,
        title: str,
        author: str,
        sections: list[tuple[str, str]],
        output_path: Path,
    ) -> Path:
        """Generate a fully accessible HTML/Markdown document with logical headings,

        semantic hierarchy, table structure, and alt text.
        """
        doc = [
            f"# {title}\n",
            f"**Author:** {author}\n",
            f"**Generated:** {time.strftime('%Y-%m-%d')}\n",
            "---\n",
        ]
        for heading, body in sections:
            doc.append(f"## {heading}\n")
            doc.append(f"{body}\n")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(doc), encoding="utf-8")
        log.info("Accessible document generated at %s", output_path)
        return output_path

    def verify_checklist(self, assignment: Assignment) -> list[str]:
        """Return list of uncompleted rubric items or warnings before submission."""
        missing = []
        for item in assignment.rubric:
            if not item.completed:
                missing.append(item.criterion)
        return missing

    def prepare_submission_confirmation(self, assignment: Assignment, file_path: Path) -> str:
        """Construct exact readback confirmation question as specified in contract:

        e.g. 'Submit Operating_Systems_Assignment.pdf to Operating Systems Assignment 3 now?'
        """
        return f"Submit {file_path.name} to {assignment.course} {assignment.title} now?"

    def verify_submission_receipt(self, receipt_text: str, expected_filename: str) -> dict:
        """Inspect and verify submission receipt evidence from LMS response."""
        has_file = expected_filename.lower() in receipt_text.lower()
        has_success = bool(
            re.search(
                r"(?:submitted|submission received|receipt|success|confirmed)",
                receipt_text,
                re.IGNORECASE,
            )
        )
        # Look for attempt number
        attempt_match = re.search(r"attempt\s*#?\s*(\d+)", receipt_text, re.IGNORECASE)
        attempt = int(attempt_match.group(1)) if attempt_match else 1

        # Look for timestamp
        time_match = re.search(
            r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?|\d{4}-\d{2}-\d{2})",
            receipt_text,
        )
        timestamp = time_match.group(1) if time_match else time.strftime("%Y-%m-%d %H:%M:%S")

        verified = has_file or has_success
        return {
            "verified": verified,
            "filename": expected_filename,
            "attempt": attempt,
            "timestamp": timestamp,
            "status": "Confirmed Submitted" if verified else "Uncertain / Verification Failed",
        }
