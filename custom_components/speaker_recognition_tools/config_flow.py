"""Config, options and subentry flows for Speaker Recognition Tools."""

from __future__ import annotations

import random
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    selector,
)

from .const import (
    CONF_ADDRESS_AS,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LEGACY_ADDRESS_AS,
    CONF_LEGACY_UNKNOWN_ADDRESS_AS,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_ALIASES,
    CONF_LINK_NAME,
    CONF_LINK_PRIVATE,
    CONF_LINK_STATE_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_ADDRESS_AS,
    CONF_USER_ID,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_ADDRESS_AS,
    DOMAIN,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_PREVIEW,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)
from .prompt import Person, build_device_prompt, build_person_prompt

_PREVIEW_UNKNOWN = "__unknown_speaker__"


class SpeakerRecognitionToolsFlow(ConfigFlow, domain=DOMAIN):
    """Pick a prompt addition to add, or preview the integration prompt."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["speaking_person", "speaking_device", "preview_full"],
        )

    async def async_step_preview_full(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Preview the integration prompt, even when no person entry exists."""
        prompt, disclaimer, note = await _full_prompt_content(self.hass, self.context)
        return self.async_show_form(
            step_id="preview_full_result",
            data_schema=vol.Schema({}),
            description_placeholders={
                "disclaimer": disclaimer,
                "prompt": prompt,
                "note": note,
            },
        )

    async def async_step_preview_full_result(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_abort(reason="preview_complete")

    async def async_step_speaking_person(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(f"{DOMAIN}_{TOOL_TYPE_PERSON}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Speaking Person",
            data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
            options={
                CONF_UNKNOWN_ADDRESS_AS: DEFAULT_UNKNOWN_ADDRESS_AS,
                CONF_DENY_UNKNOWN: False,
                CONF_REFUSAL_LINES: DEFAULT_REFUSAL_LINES,
            },
        )

    async def async_step_speaking_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(f"{DOMAIN}_{TOOL_TYPE_DEVICE}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Speaking Device", data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SpeakerRecognitionToolsOptions()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Expose person configuration and the integration-level preview on Speaking Person."""
        if config_entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
            return {
                SUBENTRY_SPEAKER: SpeakerSubentryFlow,
                SUBENTRY_ENTITY_LINK: EntityLinkSubentryFlow,
                SUBENTRY_PREVIEW: FullPromptPreviewSubentryFlow,
            }
        return {}


class SpeakerRecognitionToolsOptions(OptionsFlow):
    """Settings for Speaking Person (the gear icon)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self.config_entry.data.get(CONF_TOOL_TYPE) != TOOL_TYPE_PERSON:
            return self.async_abort(reason="no_options")
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "preview"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        opts = self.config_entry.options
        if user_input is not None:
            options = {**opts, **user_input}
            options.pop(CONF_LEGACY_UNKNOWN_ADDRESS_AS, None)
            return self.async_create_entry(data=options)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DENY_UNKNOWN, default=opts.get(CONF_DENY_UNKNOWN, False)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_UNKNOWN_ADDRESS_AS,
                    default=opts.get(
                        CONF_UNKNOWN_ADDRESS_AS,
                        opts.get(
                            CONF_LEGACY_UNKNOWN_ADDRESS_AS, DEFAULT_UNKNOWN_ADDRESS_AS
                        ),
                    ),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_REFUSAL_LINES,
                    default=opts.get(CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            selected_user_id = user_input[CONF_USER_ID]
            user_id = None if selected_user_id == _PREVIEW_UNKNOWN else selected_user_id
            people = await _configured_people(self.hass, self.config_entry)
            if user_id is not None and not any(p.user_id == user_id for p in people):
                return self.async_abort(reason="preview_person_missing")
            account = await self.hass.auth.async_get_user(user_id) if user_id else None
            prompt = build_person_prompt(
                user_id=user_id,
                user_name=(
                    account.name.split()[0] if account and account.name else None
                ),
                speakers={p.user_id: p.direct_address for p in people},
                people=people,
                unknown_address_as=self.config_entry.options.get(
                    CONF_UNKNOWN_ADDRESS_AS,
                    self.config_entry.options.get(
                        CONF_LEGACY_UNKNOWN_ADDRESS_AS, DEFAULT_UNKNOWN_ADDRESS_AS
                    ),
                ),
                deny_unknown=self.config_entry.options.get(CONF_DENY_UNKNOWN, False),
                refusal_lines=_configured_refusal_lines(self.config_entry),
            )
            return self.async_show_form(
                step_id="preview_result",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "prompt": prompt,
                },
            )
        people = await _configured_people(self.hass, self.config_entry)
        if not people:
            return self.async_abort(reason="preview_no_people")
        return self.async_show_form(
            step_id="preview",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=_PREVIEW_UNKNOWN, label="Unknown speaker"
                                ),
                                *[
                                    selector.SelectOptionDict(
                                        value=p.user_id,
                                        label=f"{p.name or p.direct_address} ({p.direct_address})",
                                    )
                                    for p in people
                                ],
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_preview_result(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_abort(reason="preview_complete")


def _configured_refusal_lines(entry) -> list[str]:
    return [
        line.strip()
        for line in entry.options.get(
            CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES
        ).splitlines()
        if line.strip()
    ] or DEFAULT_REFUSAL_LINES.splitlines()


async def _full_prompt_content(hass, context) -> tuple[str, str, str]:
    """Build only the prompt sections from configured integration APIs."""
    entries = hass.config_entries.async_entries(DOMAIN)
    person_entry = next(
        (
            entry
            for entry in entries
            if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON
        ),
        None,
    )
    device_entry = next(
        (
            entry
            for entry in entries
            if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_DEVICE
        ),
        None,
    )
    sections = []
    notes = []
    disclaimer = ""

    if person_entry:
        people = await _configured_people(hass, person_entry)
        options = person_entry.options
        account, uses_session_account = await _preview_account(hass, context)
        person_prompt = build_person_prompt(
            user_id=account.id if account else None,
            user_name=(account.name.split()[0] if account and account.name else None),
            speakers={p.user_id: p.direct_address for p in people},
            people=people,
            unknown_address_as=options.get(
                CONF_UNKNOWN_ADDRESS_AS,
                options.get(CONF_LEGACY_UNKNOWN_ADDRESS_AS, DEFAULT_UNKNOWN_ADDRESS_AS),
            ),
            deny_unknown=options.get(CONF_DENY_UNKNOWN, False),
            refusal_lines=_configured_refusal_lines(person_entry),
        )
        sections.append(person_prompt)
        notes.append(
            "Uses the signed-in Home Assistant account."
            if uses_session_account
            else "This flow did not provide the signed-in account ID, so the Home Assistant owner account is used."
        )

    if device_entry:
        device_prompt, device_note = _sample_device_prompt(hass)
        sections.append(device_prompt)
        disclaimer = (
            "Disclaimer: This is an example rendering. The Speaking Device section "
            "may show a randomly selected registered device."
        )
        notes.append(device_note)

    if not sections:
        return (
            "",
            "",
            "Neither Speaking Person nor Speaking Device is configured, so the integration adds no prompt sections.",
        )

    notes.append(
        "A conversation agent receives only APIs selected for that agent. Home Assistant "
        "appends them after the conversation prompt in the order they were added. This "
        "preview excludes the agent's own prompt and Home Assistant's API wrapper text."
    )
    return "\n\n".join(sections), disclaimer, " ".join(notes)


async def _preview_account(hass, context):
    """Use the flow's signed-in user when available, or the HA owner account."""
    if user_id := context.get("user_id"):
        if account := await hass.auth.async_get_user(user_id):
            return account, True
    users = await hass.auth.async_get_users()
    account = next((user for user in users if user.is_owner and user.is_active), None)
    return account, False


def _sample_device_prompt(hass) -> tuple[str, str]:
    """Build a device section from an Assist satellite in this installation."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    assist_device_ids = {
        entity.device_id
        for entity in entity_registry.entities.values()
        if entity.domain == "assist_satellite"
        and entity.disabled_by is None
        and entity.device_id is not None
    }
    devices = [
        device_registry.devices[device_id]
        for device_id in assist_device_ids
        if device_id in device_registry.devices
    ]
    with_area = [device for device in devices if _device_area_id(hass, device)]
    candidates = with_area or devices
    if not candidates:
        return (
            build_device_prompt(device_id=None, device_name=None),
            "No registered Assist satellite was found, so the device section says the device is unknown.",
        )
    device = random.choice(candidates)
    area_id = _device_area_id(hass, device)
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    prompt = build_device_prompt(
        device_id=device.id,
        device_name=device.name,
        area_name=area.name if area else None,
    )
    return (
        prompt,
        f"The device section uses {device.name or device.id} as an example device.",
    )


def _device_area_id(hass, device) -> str | None:
    """Return a device's assigned or inherited area."""
    return (
        dr.async_get_effective_area_id(hass, device)
        if hasattr(dr, "async_get_effective_area_id")
        else device.area_id
    )


async def _configured_people(hass, entry) -> list[Person]:
    """Build the same per-person data used by the live prompt for preview."""
    people = []
    links_by_user: dict[str, list[tuple[str, str, str, bool, tuple[str, ...]]]] = {}
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_ENTITY_LINK:
            data = sub.data
            links_by_user.setdefault(data[CONF_USER_ID], []).append(
                (
                    data[CONF_LINK_NAME],
                    data[CONF_LINK_STATE_ENTITY],
                    data[CONF_LINK_ACTION_ENTITY],
                    data.get(CONF_LINK_PRIVATE, False),
                    tuple(data.get(CONF_LINK_ALIASES, [])),
                )
            )
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_SPEAKER:
            continue
        account = await hass.auth.async_get_user(sub.data[CONF_USER_ID])
        name_parts = (account.name if account else "").split()
        name = name_parts[0] if name_parts else None
        address_as = (
            sub.data.get(CONF_ADDRESS_AS, sub.data.get(CONF_LEGACY_ADDRESS_AS)) or ""
        )
        if not name:
            continue
        entities = tuple(
            (
                entity_id,
                hass.states.get(entity_id).name
                if hass.states.get(entity_id)
                else entity_id,
            )
            for entity_id in sub.data.get(CONF_ENTITIES, [])
        )
        entity_aliases = tuple(
            (entity_id, tuple(names))
            for entity_id, names in sub.data.get(CONF_ENTITY_ALIASES, {}).items()
        )
        people.append(
            Person(
                sub.data[CONF_USER_ID],
                name,
                address_as,
                entities,
                frozenset(sub.data.get(CONF_PRIVATE_ENTITIES, [])),
                sub.data.get(CONF_THIRD_PERSON_REFERENCE) or None,
                entity_aliases,
                tuple(links_by_user.get(sub.data[CONF_USER_ID], [])),
            )
        )
    return people


def _private_is_assigned(user_input: dict[str, Any]) -> bool:
    """Private entities must also be in the person's entity list."""
    return set(user_input.get(CONF_PRIVATE_ENTITIES, [])) <= set(
        user_input.get(CONF_ENTITIES, [])
    )


def _parse_entity_aliases(
    text: str, assigned_entities: list[str]
) -> dict[str, list[str]] | None:
    """Parse one entity-id-to-alias-list mapping per line; None means invalid input."""
    assigned = set(assigned_entities)
    result: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            return None
        entity_id, raw_aliases = (part.strip() for part in line.split(":", 1))
        aliases = list(dict.fromkeys(alias.strip() for alias in raw_aliases.split(",")))
        if (
            not entity_id
            or entity_id not in assigned
            or not aliases
            or any(not alias for alias in aliases)
        ):
            return None
        result[entity_id] = aliases
    return result


def _entity_aliases_text(aliases: dict[str, list[str]] | None) -> str:
    """Format saved aliases for the multiline config-flow field."""
    return "\n".join(
        f"{entity_id}: {', '.join(names)}"
        for entity_id, names in (aliases or {}).items()
        if names
    )


def _parse_link_aliases(text: str, primary_name: str) -> tuple[str, ...]:
    """Parse comma or newline separated alternate names for a linked device."""
    aliases: list[str] = []
    seen = {primary_name.strip().casefold()}
    for raw_alias in text.replace("\n", ",").split(","):
        alias = " ".join(raw_alias.split())
        if not alias:
            continue
        key = alias.casefold()
        if key not in seen:
            aliases.append(alias)
            seen.add(key)
    return tuple(aliases)


class SpeakerSubentryFlow(ConfigSubentryFlow):
    """Add or change one person, including their optional configured address form."""

    async def _user_options(self) -> list[selector.SelectOptionDict]:
        users = await self.hass.auth.async_get_users()
        return [
            selector.SelectOptionDict(value=u.id, label=u.name or u.id)
            for u in users
            if not u.system_generated and u.is_active
        ]

    async def _subentry_title(
        self, user_id: str, address_as: str, entities: list[str], private: list[str]
    ) -> str:
        """Return the Home Assistant subentry label."""
        user = await self.hass.auth.async_get_user(user_id)
        name = user.name if user else user_id
        count = len(entities)
        amount = (
            "no entities"
            if not count
            else f"{count} {'entity' if count == 1 else 'entities'}"
        )
        if private:
            amount += f", {len(private)} private"
        return f"{f'{name}: {address_as}' if address_as else name} ({amount})"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        warnings = ""
        if user_input is not None:
            taken = {
                sub.data[CONF_USER_ID]
                for sub in entry.subentries.values()
                if sub.subentry_type == SUBENTRY_SPEAKER
            }
            aliases = _parse_entity_aliases(
                user_input.get(CONF_ENTITY_ALIASES, ""),
                user_input.get(CONF_ENTITIES, []),
            )
            if aliases is None:
                errors[CONF_ENTITY_ALIASES] = "invalid_entity_aliases"
            elif user_input[CONF_USER_ID] in taken:
                errors[CONF_USER_ID] = "already_configured"
            elif not _private_is_assigned(user_input):
                errors[CONF_PRIVATE_ENTITIES] = "private_not_assigned"
            else:
                warnings = await _entity_issues(
                    self.hass, entry, user_input.get(CONF_ENTITIES, [])
                )
                warning_key = (
                    user_input[CONF_USER_ID],
                    tuple(sorted(user_input.get(CONF_ENTITIES, []))),
                    warnings,
                )
                if (
                    warnings
                    and getattr(self, "_acknowledged_entity_warning", None)
                    != warning_key
                ):
                    self._acknowledged_entity_warning = warning_key
                    errors["base"] = "entity_warnings_acknowledge"
                else:
                    address_as = user_input.get(CONF_ADDRESS_AS, "").strip()
                    return self.async_create_entry(
                        title=await self._subentry_title(
                            user_input[CONF_USER_ID],
                            address_as,
                            user_input.get(CONF_ENTITIES, []),
                            user_input.get(CONF_PRIVATE_ENTITIES, []),
                        ),
                        data={
                            CONF_USER_ID: user_input[CONF_USER_ID],
                            CONF_ADDRESS_AS: address_as,
                            CONF_ENTITIES: user_input.get(CONF_ENTITIES, []),
                            CONF_PRIVATE_ENTITIES: user_input.get(
                                CONF_PRIVATE_ENTITIES, []
                            ),
                            **({CONF_ENTITY_ALIASES: aliases} if aliases else {}),
                            **(
                                {
                                    CONF_THIRD_PERSON_REFERENCE: user_input[
                                        CONF_THIRD_PERSON_REFERENCE
                                    ].strip()
                                }
                                if user_input.get(
                                    CONF_THIRD_PERSON_REFERENCE, ""
                                ).strip()
                                else {}
                            ),
                        },
                        unique_id=user_input[CONF_USER_ID],
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=await self._user_options())
                ),
                vol.Optional(CONF_ADDRESS_AS): selector.TextSelector(),
                vol.Optional(CONF_THIRD_PERSON_REFERENCE): selector.TextSelector(),
                vol.Optional(CONF_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(CONF_ENTITY_ALIASES): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Optional(CONF_PRIVATE_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        chosen = user_input.get(CONF_ENTITIES, []) if user_input else []
        issues = warnings or await _entity_issues(self.hass, entry, chosen)
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"entity_warnings": issues},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        warnings = ""
        aliases = (
            _parse_entity_aliases(
                user_input.get(CONF_ENTITY_ALIASES, ""),
                user_input.get(CONF_ENTITIES, []),
            )
            if user_input is not None
            else {}
        )
        if user_input is not None and aliases is None:
            errors[CONF_ENTITY_ALIASES] = "invalid_entity_aliases"
        elif user_input is not None and not _private_is_assigned(user_input):
            errors[CONF_PRIVATE_ENTITIES] = "private_not_assigned"
        elif user_input is not None:
            warnings = await _entity_issues(
                self.hass,
                entry,
                user_input.get(CONF_ENTITIES, []),
                exclude_user_id=subentry.data[CONF_USER_ID],
            )
            warning_key = (tuple(sorted(user_input.get(CONF_ENTITIES, []))), warnings)
            if (
                warnings
                and getattr(self, "_acknowledged_entity_warning", None) != warning_key
            ):
                self._acknowledged_entity_warning = warning_key
                errors["base"] = "entity_warnings_acknowledge"
            else:
                address_as = user_input.get(CONF_ADDRESS_AS, "").strip()
                user_id = subentry.data[CONF_USER_ID]
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    title=await self._subentry_title(
                        user_id,
                        address_as,
                        user_input.get(CONF_ENTITIES, []),
                        user_input.get(CONF_PRIVATE_ENTITIES, []),
                    ),
                    data={
                        CONF_USER_ID: user_id,
                        CONF_ADDRESS_AS: address_as,
                        CONF_ENTITIES: user_input.get(CONF_ENTITIES, []),
                        CONF_PRIVATE_ENTITIES: user_input.get(
                            CONF_PRIVATE_ENTITIES, []
                        ),
                        **({CONF_ENTITY_ALIASES: aliases} if aliases else {}),
                        **(
                            {
                                CONF_THIRD_PERSON_REFERENCE: user_input[
                                    CONF_THIRD_PERSON_REFERENCE
                                ].strip()
                            }
                            if user_input.get(CONF_THIRD_PERSON_REFERENCE, "").strip()
                            else {}
                        ),
                    },
                )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ADDRESS_AS,
                    description={
                        "suggested_value": subentry.data.get(
                            CONF_ADDRESS_AS,
                            subentry.data.get(CONF_LEGACY_ADDRESS_AS, ""),
                        )
                    },
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_THIRD_PERSON_REFERENCE,
                    description={
                        "suggested_value": subentry.data.get(
                            CONF_THIRD_PERSON_REFERENCE, ""
                        )
                    },
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_ENTITIES,
                    default=subentry.data.get(CONF_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_PRIVATE_ENTITIES,
                    default=subentry.data.get(CONF_PRIVATE_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_ENTITY_ALIASES,
                    default=_entity_aliases_text(
                        subentry.data.get(CONF_ENTITY_ALIASES)
                    ),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )
        chosen = (
            user_input.get(CONF_ENTITIES, [])
            if user_input
            else subentry.data.get(CONF_ENTITIES, [])
        )
        issues = warnings or await _entity_issues(
            self.hass, entry, chosen, exclude_user_id=subentry.data[CONF_USER_ID]
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={"entity_warnings": issues},
        )


class EntityLinkSubentryFlow(ConfigSubentryFlow):
    """Link one spoken device name to separate status and action entities."""

    async def _person_options(self) -> list[selector.SelectOptionDict]:
        options = []
        for sub in self._get_entry().subentries.values():
            if sub.subentry_type != SUBENTRY_SPEAKER:
                continue
            user = await self.hass.auth.async_get_user(sub.data[CONF_USER_ID])
            if user and user.is_active:
                options.append(
                    selector.SelectOptionDict(
                        value=user.id,
                        label=(
                            f"{user.name} ({sub.data.get(CONF_ADDRESS_AS, '')})"
                            if sub.data.get(CONF_ADDRESS_AS)
                            else user.name
                        ),
                    )
                )
        return options

    async def _entry_title(self, name: str, user_id: str) -> str:
        """Include the owner's first name in the link row shown in Home Assistant."""
        user = await self.hass.auth.async_get_user(user_id)
        parts = (user.name if user else user_id).split()
        owner = parts[0] if parts else "Person"
        return f"{name} ({owner})"

    def _link_names_in_use(
        self, user_id: str, names: list[str], exclude: str | None = None
    ) -> bool:
        requested = {name.strip().casefold() for name in names if name.strip()}
        return any(
            sub.subentry_type == SUBENTRY_ENTITY_LINK
            and sub.subentry_id != exclude
            and sub.data.get(CONF_USER_ID) == user_id
            and requested.intersection(
                {
                    sub.data.get(CONF_LINK_NAME, "").strip().casefold(),
                    *(
                        alias.strip().casefold()
                        for alias in sub.data.get(CONF_LINK_ALIASES, [])
                    ),
                }
            )
            for sub in self._get_entry().subentries.values()
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.get(CONF_LINK_NAME, "").strip()
            aliases = _parse_link_aliases(user_input.get(CONF_LINK_ALIASES, ""), name)
            state_entity = user_input.get(CONF_LINK_STATE_ENTITY)
            action_entity = user_input.get(CONF_LINK_ACTION_ENTITY)
            if not name:
                errors[CONF_LINK_NAME] = "link_name_required"
            elif self._link_names_in_use(user_input[CONF_USER_ID], [name, *aliases]):
                errors[CONF_LINK_NAME] = "duplicate_link_name"
            elif state_entity == action_entity:
                errors[CONF_LINK_ACTION_ENTITY] = "link_entities_must_differ"
            else:
                return self.async_create_entry(
                    title=await self._entry_title(name, user_input[CONF_USER_ID]),
                    data={
                        CONF_USER_ID: user_input[CONF_USER_ID],
                        CONF_LINK_NAME: name,
                        CONF_LINK_ALIASES: list(aliases),
                        CONF_LINK_STATE_ENTITY: state_entity,
                        CONF_LINK_ACTION_ENTITY: action_entity,
                        CONF_LINK_PRIVATE: user_input.get(CONF_LINK_PRIVATE, False),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=await self._person_options())
                ),
                vol.Required(CONF_LINK_NAME): selector.TextSelector(),
                vol.Optional(CONF_LINK_ALIASES, default=""): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Required(CONF_LINK_STATE_ENTITY): selector.EntitySelector(),
                vol.Required(CONF_LINK_ACTION_ENTITY): selector.EntitySelector(),
                vol.Optional(
                    CONF_LINK_PRIVATE, default=False
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.get(CONF_LINK_NAME, "").strip()
            aliases = _parse_link_aliases(user_input.get(CONF_LINK_ALIASES, ""), name)
            state_entity = user_input.get(CONF_LINK_STATE_ENTITY)
            action_entity = user_input.get(CONF_LINK_ACTION_ENTITY)
            if not name:
                errors[CONF_LINK_NAME] = "link_name_required"
            elif self._link_names_in_use(
                user_input[CONF_USER_ID], [name, *aliases], exclude=subentry.subentry_id
            ):
                errors[CONF_LINK_NAME] = "duplicate_link_name"
            elif state_entity == action_entity:
                errors[CONF_LINK_ACTION_ENTITY] = "link_entities_must_differ"
            else:
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    title=await self._entry_title(name, user_input[CONF_USER_ID]),
                    data={
                        CONF_USER_ID: user_input[CONF_USER_ID],
                        CONF_LINK_NAME: name,
                        CONF_LINK_ALIASES: list(aliases),
                        CONF_LINK_STATE_ENTITY: state_entity,
                        CONF_LINK_ACTION_ENTITY: action_entity,
                        CONF_LINK_PRIVATE: user_input.get(CONF_LINK_PRIVATE, False),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USER_ID,
                    default=data[CONF_USER_ID],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=await self._person_options())
                ),
                vol.Required(
                    CONF_LINK_NAME,
                    default=data[CONF_LINK_NAME],
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_LINK_ALIASES,
                    default=", ".join(data.get(CONF_LINK_ALIASES, [])),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_LINK_STATE_ENTITY,
                    default=data[CONF_LINK_STATE_ENTITY],
                ): selector.EntitySelector(),
                vol.Required(
                    CONF_LINK_ACTION_ENTITY,
                    default=data[CONF_LINK_ACTION_ENTITY],
                ): selector.EntitySelector(),
                vol.Optional(
                    CONF_LINK_PRIVATE,
                    default=data.get(CONF_LINK_PRIVATE, False),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )


class FullPromptPreviewSubentryFlow(ConfigSubentryFlow):
    """Show the full prompt from the integration page without creating a subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            return self.async_abort(reason="preview_complete")
        prompt, disclaimer, note = await _full_prompt_content(self.hass, self.context)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "disclaimer": disclaimer,
                "prompt": prompt,
                "note": note,
            },
        )


async def _entity_issues(
    hass, entry, entities: list[str], exclude_user_id: str | None = None
) -> str:
    """Describe stale entity IDs and assignments shared by multiple people."""
    stale = sorted(
        entity_id for entity_id in entities if hass.states.get(entity_id) is None
    )
    owners = {}
    for sub in entry.subentries.values():
        if (
            sub.subentry_type != SUBENTRY_SPEAKER
            or sub.data[CONF_USER_ID] == exclude_user_id
        ):
            continue
        for entity_id in sub.data.get(CONF_ENTITIES, []):
            if entity_id in entities:
                owners.setdefault(entity_id, []).append(sub.title)
    shared = sorted(owners)
    messages = []
    if stale:
        messages.append("No current state found for: " + ", ".join(stale))
    if shared:
        messages.append("Also assigned to another person: " + ", ".join(shared))
    return "\n".join(messages)
