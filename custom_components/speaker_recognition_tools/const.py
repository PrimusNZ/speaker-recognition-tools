"""Constants for Speaker Recognition Tools."""

DOMAIN = "speaker_recognition_tools"
CONF_TOOL_TYPE = "tool_type"
TOOL_TYPE_PERSON = "person"
TOOL_TYPE_DEVICE = "device"

PERSON_API_ID = f"{DOMAIN}_person"
PERSON_API_NAME = "Speaking Person"
DEVICE_API_ID = f"{DOMAIN}_device"
DEVICE_API_NAME = "Speaking Device"

SUBENTRY_SPEAKER = "speaker"  # one subentry per person: data {user_id, address_as, entities, private_entities}
SUBENTRY_ENTITY_LINK = (
    "entity_link"  # one named device link with a status entity and an action entity
)
SUBENTRY_PREVIEW = (
    "full_prompt_preview"  # transient integration-level prompt preview flow
)
CONF_USER_ID = "user_id"
CONF_ADDRESS_AS = "address_as"  # Optional direct-address form shown as "Address as".
CONF_LEGACY_ADDRESS_AS = (
    "title"  # Read existing entries created before the field was renamed.
)
CONF_THIRD_PERSON_REFERENCE = "third_person_reference"
CONF_ENTITIES = "entities"  # optional list of entity ids
CONF_ENTITY_ALIASES = "entity_aliases"  # entity id to alternate names
CONF_PRIVATE_ENTITIES = "private_entities"  # subset of entities only the owner may use
CONF_CONFIRM_ENTITIES = "confirm_entities"  # subset needing a spoken yes to control
CONF_ADMIN_ENTITIES = "admin_entities"  # subset only administrators may control
CONF_NOTIFY_SERVICE = (
    "notify_service"  # optional notify action for messages, e.g. notify.mobile_app_x
)
CONF_LINK_NAME = "link_name"
CONF_LINK_ALIASES = "link_aliases"  # alternate names for the linked device
CONF_LINK_STATE_ENTITY = "state_entity"
CONF_LINK_ACTION_ENTITY = "action_entity"
CONF_LINK_PRIVATE = "private"
CONF_LINK_CONFIRM = "confirm"  # actions need a spoken yes
CONF_LINK_ADMIN_ONLY = "admin_only"  # only administrators may use the action entity
CONF_UNKNOWN_ADDRESS_AS = "unknown_address_as"
CONF_LEGACY_UNKNOWN_ADDRESS_AS = (
    "unknown_title"  # Read existing options saved before the field was renamed.
)
CONF_DENY_UNKNOWN = "deny_unknown"
CONF_REFUSAL_LINES = "refusal_lines"  # one line per row
CONF_MIN_CONFIDENCE = (
    "min_confidence"  # below this, writes also confirm identity; 0 is off
)

EVENT_SPEAKER = f"{DOMAIN}_speaker"  # fired once per Speaking Person turn
SIGNAL_SPEAKER = (
    f"{DOMAIN}_speaker_{{}}"  # dispatcher signal, formatted with the entry id
)

DEFAULT_UNKNOWN_ADDRESS_AS = "Unknown Person"
DEFAULT_REFUSAL_LINES = (
    "That request cannot be completed.\n"
    "I'm unable to perform that action.\n"
    "That action is not permitted.\n"
    "I'm unable to proceed with that request.\n"
    "That operation is restricted.\n"
    "I cannot carry out that instruction.\n"
    "That request cannot be fulfilled.\n"
    "I'm unable to make that change.\n"
    "That action is not available.\n"
    "I cannot assist with that request.\n"
    "That operation cannot be performed.\n"
    "I'm unable to execute that command.\n"
    "That request is not permitted.\n"
    "I cannot proceed with that action.\n"
    "Access to that function is restricted.\n"
    "I'm unable to fulfil that instruction.\n"
    "That action cannot be authorised.\n"
    "I cannot provide access to that function.\n"
    "That command cannot be executed.\n"
    "I'm unable to comply with that request."
)
