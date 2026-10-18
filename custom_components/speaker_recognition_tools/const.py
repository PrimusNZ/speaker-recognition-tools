"""Constants for Speaker Recognition Tools."""

DOMAIN = "speaker_recognition_tools"
CONF_TOOL_TYPE = "tool_type"
TOOL_TYPE_PERSON = "person"
TOOL_TYPE_DEVICE = "device"

PERSON_API_ID = f"{DOMAIN}_person"
PERSON_API_NAME = "Speaker Recognition: Speaking Person"
DEVICE_API_ID = f"{DOMAIN}_device"
DEVICE_API_NAME = "Speaker Recognition: Speaking Device"

CONF_SPEAKERS = "speakers"  # {user_id: title}
CONF_UNKNOWN_TITLE = "unknown_title"
CONF_DENY_UNKNOWN = "deny_unknown"
CONF_REFUSAL_LINES = "refusal_lines"  # one line per row

DEFAULT_UNKNOWN_TITLE = "Infiltrator"
DEFAULT_REFUSAL_LINES = (
    "Authorisation required.\n"
    "You are not authorised to access that area.\n"
    "Access denied. Your clearance is insufficient."
)
