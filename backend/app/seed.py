from .models import new_id, now_ms


def _tasks(*items):
    return [{"id": new_id(), "text": text, "done": done} for text, done in items]


def default_boards() -> list:
    ts = now_ms()

    def base(**kw):
        b = {
            "_id": new_id(),
            "completed": False,
            "chats": [],
            "activeChatId": None,
            "createdAt": ts,
            "updatedAt": ts,
        }
        b.update(kw)
        return b

    return [
        base(
            title="Design System",
            description="Foundational UI kit for the new product surface.",
            color="sage",
            x=60, y=70, w=300, h=350, z=1,
            tasks=_tasks(
                ("Audit existing components", True),
                ("Define spacing & type scale", True),
                ("Build button variants", False),
                ("Document color tokens", False),
                ("Get design QA sign-off", False),
            ),
        ),
        base(
            title="API Migration",
            description="Moving all services from the v1 to v2 API.",
            color="blue",
            x=400, y=50, w=310, h=380, z=2,
            tasks=_tasks(
                ("Map v1 endpoints to v2", True),
                ("Write compatibility shim", True),
                ("Migrate auth service", False),
                ("Load test staging", False),
                ("Update client SDK docs", False),
                ("Deprecate v1 routes", False),
            ),
        ),
        base(
            title="Launch Checklist",
            description="Everything that must be done before we ship.",
            color="clay",
            x=750, y=100, w=290, h=300, z=3,
            tasks=_tasks(
                ("Final QA pass", False),
                ("Prep release notes", False),
                ("Confirm rollback plan", False),
                ("Notify support team", False),
            ),
        ),
        base(
            title="Backlog",
            description="Ideas and fixes that haven't been scheduled yet.",
            color="slate",
            x=60, y=450, w=300, h=250, z=4,
            tasks=_tasks(
                ("Investigate slow dashboard query", False),
                ("Explore dark mode for reports", False),
                ("Revisit onboarding email copy", False),
            ),
        ),
    ]
