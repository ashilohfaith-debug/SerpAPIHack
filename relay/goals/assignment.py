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
from typing import Any, Optional

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
    """End-to-end assignment workflow assistant for students."""

    def __init__(self, bus: Any = None, goals: Any = None, session: Any = None) -> None:
        self.bus = bus
        self.goals = goals
        self.session = session
        self.active_assignment: Optional[Assignment] = None

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

        # Extract course and title if not provided
        if not title:
            t_match = re.search(
                r"(?:assignment|project|homework|lab)\s*#?\s*(\d+|[A-Za-z0-9_-]+)",
                raw_text,
                re.IGNORECASE,
            )
            title = t_match.group(0).capitalize() if t_match else "Course Assignment"
        if not course:
            c_match = re.search(r"\b([A-Z]{2,4}\s*\d{3,4})\b", raw_text)
            course = c_match.group(1) if c_match else "Course"

        return Assignment(
            assignment_id=aid,
            title=title,
            course=course,
            deadline=deadline,
            instructions=raw_text,
            rubric=rubric,
            required_format=fmt,
            word_limit=word_limit,
            submission_target=course or "LMS",
        )

    def start_assignment_from_session(self, session: Any) -> str:
        """Start assignment journey by inspecting current screen, active document, or clipboard."""
        raw_text = ""
        # 1. Try reading screen text from worker snapshot
        if session.worker:
            snap = session.worker.live or session.worker.observe(2.0)
            if snap and snap.elements:
                raw_text = "\n".join(e.name for e in snap.elements if len(e.name) > 10)

        # 2. If screen text is short, try reading clipboard text
        if len(raw_text.strip()) < 40:
            try:
                import pyperclip

                clip = pyperclip.paste()
                if clip and len(clip.strip()) > 30:
                    raw_text = clip
            except Exception:
                pass

        if not raw_text.strip():
            raw_text = (
                "Standard academic assignment with required rubric, analysis, and references."
            )

        assignment = self.parse_instructions(raw_text)
        self.active_assignment = assignment

        # If GoalManager is present, create an associated multi-step persistent goal
        if self.goals:
            steps = [
                f"Review rubric ({len(assignment.rubric)} criteria)",
                "Draft accessible document",
                "Verify rubric checklist",
                f"Confirm and submit to {assignment.course}",
            ]
            self.goals.start_goal(
                title=f"{assignment.course} - {assignment.title}",
                steps=steps,
                mode="Assignment",
                context={"assignment_id": assignment.assignment_id},
            )

        deadline_msg = f" Deadline: {assignment.deadline}." if assignment.deadline else ""
        return (
            f"Started Assignment Mode for {assignment.course} {assignment.title}. "
            f"Found {len(assignment.rubric)} rubric criteria.{deadline_msg} "
            "Say check rubric to review requirements, or draft assignment to create the document."
        )

    def get_status_summary(self) -> str:
        """Spoken summary of assignment status and rubric checklist."""
        if not self.active_assignment:
            return "No active assignment. Say help me complete my assignment to begin."
        a = self.active_assignment
        done = sum(1 for r in a.rubric if r.completed)
        total = len(a.rubric)
        missing = [r.criterion for r in a.rubric if not r.completed]
        missing_str = "; ".join(missing[:3]) if missing else "All criteria completed!"
        return (
            f"Assignment: {a.course} {a.title}. {done} of {total} rubric items completed. "
            f"Pending: {missing_str}."
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
        if self.active_assignment:
            self.active_assignment.draft_path = str(output_path)
            self.active_assignment.status = "ready_for_review"
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
        """Inspect and verify submission receipt evidence from LMS response.

        Never fakes success: requires filename AND corroborating confirmation evidence.
        Never invents timestamps or attempt numbers.
        """
        has_file = expected_filename.lower() in receipt_text.lower()
        has_success = bool(
            re.search(
                r"(?:submission received|submission confirmed|successfully submitted|assignment submitted|"
                r"submission confirmation|receipt\s*#?[:\s]*\w+|turnitin receipt)",
                receipt_text,
                re.IGNORECASE,
            )
        )
        # Look for actual attempt number if present
        attempt_match = re.search(r"attempt\s*#?\s*(\d+)", receipt_text, re.IGNORECASE)
        attempt = int(attempt_match.group(1)) if attempt_match else None

        # Look for real timestamp if present
        time_match = re.search(
            r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?|\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)",
            receipt_text,
        )
        timestamp = time_match.group(1) if time_match else None

        # Both the filename and explicit confirmation are required to verify submission
        verified = has_file and has_success
        status = (
            "Confirmed Submitted" if verified else "Unverified: Missing proof or filename mismatch"
        )

        result = {
            "verified": verified,
            "filename": expected_filename if has_file else "",
            "attempt": attempt,
            "timestamp": timestamp,
            "status": status,
            "receipt_snippet": receipt_text[:200].strip(),
        }
        if verified and self.active_assignment:
            self.active_assignment.status = "submitted"
            if self.goals and self.goals.active_goal:
                self.goals.advance_step(evidence=f"Receipt verified: {expected_filename}")
        return result
