"""LLM tools that work on a person's assigned entities and enforce who may use them.

A person's entities are shared unless they are marked private. A private entity
can only be used by its owner. Every tool checks this itself, so a request about
someone else's private calendar is refused whatever the model asks for.
"""

from homeassistant.helpers import llm

from .calendar_tools import (
    CheckCalendarAvailabilityTool,
    CreateCalendarEventTool,
    DeleteCalendarEventTool,
    GetCalendarEventsTool,
    SearchCalendarEventsTool,
    UpdateCalendarEventTool,
)
from .entity_tools import ControlAssignedEntityTool, GetEntityStateTool
from .location_tools import GetPersonLocationHistoryTool, GetPersonLocationTool
from .message_tools import SendMessageToPersonTool
from .prompt import Person
from .todo_tools import (
    AddTodoItemTool,
    GetTodoItemsTool,
    RemoveTodoItemTool,
    UpdateTodoItemTool,
)
from .tool_base import Household


def build_tools(
    people: list[Person], speaker: Person, *, uncertain: bool = False
) -> list[llm.Tool]:
    """Return the tools for one recognised speaker."""
    household = Household(people, speaker, uncertain=uncertain)
    return [
        GetEntityStateTool(household),
        ControlAssignedEntityTool(household),
        GetCalendarEventsTool(household),
        SearchCalendarEventsTool(household),
        CheckCalendarAvailabilityTool(household),
        CreateCalendarEventTool(household),
        UpdateCalendarEventTool(household),
        DeleteCalendarEventTool(household),
        GetPersonLocationTool(household),
        GetPersonLocationHistoryTool(household),
        GetTodoItemsTool(household),
        AddTodoItemTool(household),
        UpdateTodoItemTool(household),
        RemoveTodoItemTool(household),
        SendMessageToPersonTool(household),
    ]
