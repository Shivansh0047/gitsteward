from typing import TypedDict, Literal

class SectionResult(TypedDict):
    anchor: str
    status: Literal["updated", "not_stale"]
    reasons: list[str]

class WorkflowState(TypedDict):
    run_id: str                    # the triggering commit SHA — also our thread_id for checkpointing
    repo: str                      # "owner/name"
    changed_files: list[str]
    diffs: dict[str, str]           # {file_path: diff_patch}
    section_results: dict[str, SectionResult]   # {anchor: result}, populated as nodes run
    branch: str | None              # review branch name, once determined
    pr_number: int | None           # set once the PR is opened
    status: Literal["running", "waiting_approval", "done"]