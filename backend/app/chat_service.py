from typing import AsyncGenerator, List

import anthropic

from . import config

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None


def build_board_context(board: dict) -> str:
    lines = [
        "You are a helpful assistant embedded in a project board app called Scatterboard. "
        "Only discuss the board described below.",
        f"Board title: {board.get('title') or 'Untitled board'}",
    ]
    if board.get("description"):
        lines.append(f"Board description: {board['description']}")

    tasks = board.get("tasks", [])
    open_tasks = [t for t in tasks if not t.get("done")]
    done_tasks = [t for t in tasks if t.get("done")]

    lines.append(f"Open tasks ({len(open_tasks)}):")
    if open_tasks:
        lines.extend(f"- {t.get('text', '')}" for t in open_tasks)
    else:
        lines.append("(none)")

    if done_tasks:
        lines.append(f"Completed tasks ({len(done_tasks)}):")
        lines.extend(f"- {t.get('text', '')}" for t in done_tasks)

    lines.append(
        "Answer questions, help prioritize, and help draft or think through this board's work. "
        "You cannot edit the board yourself — if something should change, tell the user what "
        "to add or edit so they can do it."
    )
    return "\n".join(lines)


async def stream_reply(board: dict, history: List[dict]) -> AsyncGenerator[str, None]:
    if _client is None:
        yield "Chat isn't configured — the server is missing an ANTHROPIC_API_KEY."
        return

    system_prompt = build_board_context(board)
    messages = [{"role": m["role"], "content": m["text"]} for m in history]

    try:
        async with _client.messages.stream(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except anthropic.APIStatusError as e:
        if e.status_code == 429:
            yield "You're sending messages a bit fast — please wait a moment and try again."
        else:
            yield f"Something went wrong reaching the assistant ({e.status_code})."
    except Exception:
        yield "Something went wrong reaching the assistant."
