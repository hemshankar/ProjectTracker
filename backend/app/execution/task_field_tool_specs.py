"""Declarations for the two tools that let the agent maintain a task's own
Description and Execution Summary. Execution lives in `task_field_tools`
(it needs the board/task the call is for, which a plain `ToolSpec.simulate`
doesn't get)."""
from .tool_spec import ToolSpec

UPDATE_DESCRIPTION = "update_task_description"
SET_SUMMARY = "set_execution_summary"

TASK_FIELD_TOOLS = {
    UPDATE_DESCRIPTION: ToolSpec(
        name=UPDATE_DESCRIPTION,
        description=(
            "Replace this task's Description — the detailed context the user and you build up as the "
            "task gets clearer (requirements, constraints, decisions, who/what/where). Send the FULL "
            "new text; it overwrites the old one, but every version is kept in history. Pass the "
            "`base_version` shown with the current description in your instructions. If you drop "
            "anything from the existing text, you MUST say what and why in `removed_summary`, or the "
            "call is refused. If someone edited the description since, the call is refused with the "
            "latest text so you can merge their changes in and retry."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The full new description, in markdown"},
                "base_version": {"type": "integer", "description": "The description version you based this on"},
                "removed_summary": {
                    "type": "string",
                    "description": "What you removed from the old text and why. Required if anything was removed.",
                },
            },
            "required": ["content", "base_version"],
        },
        mutating=False,
        simulate=lambda p: "Description updated.",
    ),
    SET_SUMMARY: ToolSpec(
        name=SET_SUMMARY,
        description=(
            "Record this task's execution summary: what was done, the outcome, anything the user "
            "should know or follow up on. Call it once, right before you finish the task. If you are "
            "stopping because the task failed or is blocked on someone outside this system, summarize "
            "what you did and what is blocking instead. Markdown."
        ),
        input_schema={
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "The execution summary, in markdown"}},
            "required": ["summary"],
        },
        mutating=False,
        simulate=lambda p: "Execution summary recorded.",
    ),
}
