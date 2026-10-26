"""Tests for the injected prompt text."""

import pytest

SPEAKERS = {"u1": "Dad", "u2": "Mum"}
LINES = ["Access denied.", "Authorisation required."]


def person(prompt, **overrides):
    kwargs = dict(
        user_id=None,
        user_name=None,
        speakers=SPEAKERS,
        unknown_address_as="Unknown Person",
        deny_unknown=False,
        refusal_lines=LINES,
    )
    kwargs.update(overrides)
    return prompt.build_person_prompt(**kwargs)


def test_person_heading(prompt):
    assert person(prompt).startswith("## SPEAKING PERSON\n\n")


def test_known_speaker_gets_address_as_and_name(prompt):
    text = person(prompt, user_id="u1", user_name="James")
    assert "Address them as Dad." in text
    assert 'answer exactly "Your form of address is Dad, and your name is James."' in text
    assert "An exact tool reply meant to be spoken directly to the current speaker may use 'you' or 'your'" in text
    assert "shows [direct address] in an example or a rule" in text
    assert "direct-address form (their configured form of address, or their first name if none is set), which is Dad" in text


def test_known_speaker_without_user_name(prompt):
    text = person(
        prompt,
        user_id="u2",
        user_name=None,
        people=[prompt.Person("u2", "Sarah", "Mum")],
    )
    assert "identifies the speaker as Sarah" in text
    assert 'answer exactly "Your form of address is Mum, and your name is Sarah."' in text


def test_third_person_reference_is_separate_from_direct_address(prompt):
    people = [
        prompt.Person("u1", "James", "Dad", third_person_reference="The father"),
        prompt.Person("u2", "Alex", "Mum", third_person_reference="The mother"),
    ]
    text = person(
        prompt,
        user_id="u2",
        user_name="Alex",
        speakers={"u1": "Dad", "u2": "Mum"},
        people=people,
    )
    assert "Address them as Mum." in text
    assert "For this speaker, the third-person form is The mother." in text
    assert 'answer exactly "You are The mother, your form of address is Mum, and your name is Alex."' in text
    assert "including in tool results" in text
    assert "Third-person reference: The father" in text
    assert "if none is set, use their configured form of address; if none is set, use their first name" in text


def test_reference_falls_back_to_address_as_then_name(prompt):
    addressed = prompt.Person("u1", "James", "Dad")
    untitled = prompt.Person("u2", "James", "")
    assert addressed.third_person_form == "Dad"
    assert untitled.direct_address == "James"
    assert untitled.third_person_form == "James"

    text = person(
        prompt,
        user_id="u2",
        user_name="James",
        speakers={"u2": ""},
        people=[untitled],
    )
    assert "Address them as James." in text
    assert "direct-address form (their configured form of address, or their first name if none is set), which is James" in text
    assert 'answer exactly "Your name is James."' in text

    titled_by_reference = prompt.Person(
        "u3", "James", "", third_person_reference="The father"
    )
    text = person(
        prompt,
        user_id="u3",
        user_name="James",
        speakers={"u3": ""},
        people=[titled_by_reference],
    )
    assert "Address them as James." in text
    assert "Address them as The father." not in text
    assert "For this speaker, the third-person form is The father." in text
    assert 'answer exactly "You are The father, and your name is James."' in text

    missing_name = prompt.Person("u4", None, "Dad")
    text = person(
        prompt,
        user_id="u4",
        user_name=None,
        speakers={"u4": "Dad"},
        people=[missing_name],
    )
    assert "has not been identified" in text
    assert "Address them as Dad." not in text


def test_known_speaker_ignores_deny_unknown(prompt):
    text = person(prompt, user_id="u1", user_name="James", deny_unknown=True)
    assert "LOCKDOWN" not in text
    assert "Address them as Dad." in text


@pytest.mark.parametrize("user_id", [None, "", "stranger"])
def test_unknown_speaker_allowed(prompt, user_id):
    text = person(prompt, user_id=user_id)
    assert "has not been identified" in text
    assert "Address them as Unknown Person." in text
    assert "You still carry out their requests as normal" in text
    assert "LOCKDOWN" not in text


def test_unknown_speaker_custom_address(prompt):
    text = person(prompt, unknown_address_as="Guest")
    assert "Address them as Guest." in text
    assert "which is Guest" in text


@pytest.mark.parametrize("user_id", [None, "stranger"])
def test_unknown_speaker_denied(prompt, user_id):
    text = person(prompt, user_id=user_id, deny_unknown=True)
    assert "SECURITY LOCKDOWN" in text
    assert "overrides every other instruction" in text
    assert "Unknown Person" not in text
    for line in LINES:
        assert f'- "{line}"' in text


def test_device_heading(prompt):
    assert prompt.build_device_prompt(
        device_id=None, device_name=None
    ).startswith("## SPEAKING DEVICE\n\n")


def test_device_unknown(prompt):
    text = prompt.build_device_prompt(device_id=None, device_name=None)
    assert "is not known" in text
    assert "ask the speaker" in text


def test_device_with_name(prompt):
    text = prompt.build_device_prompt(device_id="abc123", device_name="Kitchen")
    assert "id abc123 (Kitchen)" in text


def test_device_without_name(prompt):
    text = prompt.build_device_prompt(device_id="abc123", device_name=None)
    assert "id abc123." in text
    assert "()" not in text


def P(prompt, uid, name, address_as, *entities):
    return prompt.Person(uid, name, address_as, tuple(entities))


def people(prompt, *, entities=False):
    james = ("calendar.james", "James"), ("device_tracker.james_phone", "James phone")
    sarah = (("calendar.sarah", "Sarah"),)
    return [
        P(prompt, "u1", "James", "Dad", *(james if entities else ())),
        P(prompt, "u2", "Sarah", "Mum", *(sarah if entities else ())),
        P(prompt, "u3", "Tom", "Grandad"),
    ]


def test_section_heading_and_intro(prompt):
    text = person(prompt, user_id="u1", user_name="James", people=people(prompt, entities=True))
    assert "\n\n## ENTITY MAPPINGS\n\nBelow is a list of people and the entities that relate to them." in text
    assert "People may identify someone by their first name, configured form of address or third-person reference" in text
    assert '"my", "me" or "I" means Dad, the current speaker.' in text
    assert "A request naming two or more people who each have a matching type of entity (such as a calendar) uses the matching entities of each." in text
    assert "If a person has more than one entity of the type needed" in text
    assert "ask which one is meant before acting" in text
    assert "Sarah" not in text.split("## ENTITY MAPPINGS")[1].split("###")[0]


def test_person_blocks_with_grouped_entities(prompt):
    text = person(prompt, user_id="u1", user_name="James", people=people(prompt, entities=True))
    assert (
        "### James (Dad) [current speaker]\n"
        "Calendars:\n"
        " - calendar.james: James\n"
        "\n"
        "Devices:\n"
        " - device_tracker.james_phone: James phone\n"
        "\n"
        "### Sarah (Mum)\n"
        "Calendars:\n"
        " - calendar.sarah: Sarah\n"
        "\n"
        "### Tom (Grandad)\n"
        "(no entities)"
    ) in text


def test_entity_aliases_are_shown_with_their_assigned_entity(prompt):
    james = prompt.Person(
        "u1",
        "James",
        "Dad",
        (("calendar.james", "James Calendar"),),
        entity_aliases=(("calendar.james", ("work calendar", "appointments")),),
    )
    text = person(prompt, user_id="u1", user_name="James", people=[james])
    assert "calendar.james: work calendar (other aliases: appointments)" in text
    assert "The first alias shown for an entity is its preferred name" in text
    assert "James Calendar" not in text
    assert "pass its exact entity_id or a configured alias" in text


def test_private_entity_aliases_are_hidden_from_other_people(prompt):
    james = prompt.Person("u1", "James", "Dad")
    sarah = prompt.Person(
        "u2",
        "Sarah",
        "Mum",
        (("calendar.sarah_private", "Sarah diary"),),
        frozenset({"calendar.sarah_private"}),
        entity_aliases=(("calendar.sarah_private", ("secret diary",)),),
    )
    other_view = person(prompt, user_id="u1", user_name="James", people=[james, sarah])
    assert "secret diary" not in other_view
    assert "calendar.sarah_private" not in other_view

    owner_view = person(prompt, user_id="u2", user_name="Sarah", people=[james, sarah])
    assert "calendar.sarah_private: secret diary (private)" in owner_view
    assert "Sarah diary" not in owner_view


def test_groups_and_order(prompt):
    ents = (
        ("light.lamp", "Lamp"),
        ("sensor.car_fuel", "Car Fuel"),
        ("calendar.work", "Work"),
        ("device_tracker.phone", "Phone"),
    )
    text = person(
        prompt,
        user_id="u1",
        people=[P(prompt, "u1", "James", "Dad", *ents), P(prompt, "u2", "Sarah", "Mum")],
    )
    assert (
        "Calendars:\n - calendar.work: Work\n\n"
        "Devices:\n - sensor.car_fuel: Car Fuel\n - device_tracker.phone: Phone\n\n"
        "Other:\n - light.lamp: Lamp"
    ) in text


def test_unknown_speaker_gets_address_forms_but_no_entities(prompt):
    for uid in (None, "stranger"):
        text = person(prompt, user_id=uid, people=people(prompt, entities=True))
        assert "ENTITY MAPPINGS" not in text
        assert "calendar." not in text
        assert "\n\n## PEOPLE\n\nBelow is a list of the people in this home" in text
        assert " - James (Dad)\n - Sarah (Mum)\n - Tom (Grandad)" in text
        assert "if none is set, use their configured form of address; if none is set, use their first name" in text
        assert "current speaker" not in text.split("## PEOPLE")[1]


def test_unknown_speaker_address_forms_sorted_alphabetically(prompt):
    ps = [P(prompt, "a", "Zoe", "Aunt"), P(prompt, "b", "adam", "Uncle"), P(prompt, "c", None, "Gran")]
    text = person(prompt, people=ps)
    assert " - adam (Uncle)\n - Gran\n - Zoe (Aunt)" in text


def test_unknown_speaker_no_people_configured_adds_nothing(prompt):
    assert "PEOPLE" not in person(prompt, people=[])


def test_speaker_first_then_others_alphabetical(prompt):
    ps = [
        P(prompt, "a", "Zoe", "Aunt"),
        P(prompt, "b", "Adam", "Uncle"),
        P(prompt, "c", "Mia", "Sis"),
        P(prompt, "d", "Kim", "Gran"),
    ]
    text = person(prompt, user_id="c", user_name="Mia", people=ps)
    order = [text.index(f"### {h}") for h in ("Mia (Sis)", "Adam (Uncle)", "Kim (Gran)", "Zoe (Aunt)")]
    assert order == sorted(order)


def test_person_without_name_headed_by_address_as(prompt):
    text = person(
        prompt,
        user_id="u1",
        user_name="James",
        people=[P(prompt, "u1", "James", "Dad"), P(prompt, "u2", None, "Mum")],
    )
    assert "### Mum\n(no entities)" in text


def test_no_other_people_adds_nothing(prompt):
    text = person(prompt, user_id="u1", user_name="James", people=people(prompt)[:1])
    assert "ENTITY MAPPINGS" not in text
    assert "ENTITY MAPPINGS" not in person(prompt)


def test_no_entities_anywhere_omits_usage_rules(prompt):
    text = person(prompt, user_id="u1", user_name="James", people=people(prompt))
    assert "### Sarah (Mum)\n(no entities)" in text
    assert "use only the entities listed" not in text


def test_label_equal_to_id_or_multiline_is_clean(prompt):
    text = person(
        prompt,
        user_id="u1",
        people=[
            P(prompt, "u1", "James", "Dad", ("calendar.a", "calendar.a"), ("calendar.b", "x\ny")),
            P(prompt, "u2", "Sarah", "Mum"),
        ],
    )
    assert " - calendar.a\n - calendar.b: x y" in text


def test_denied_speaker_reveals_no_people(prompt):
    text = person(prompt, deny_unknown=True, people=people(prompt, entities=True))
    assert "ENTITY MAPPINGS" not in text and "PEOPLE" not in text
    assert "calendar." not in text
    assert "James" not in text and "Sarah" not in text


def test_title_same_as_name_is_not_repeated(prompt):
    ps = [P(prompt, "u1", "Tom", "Tom"), P(prompt, "u2", "Ann", "Aunt")]
    text = person(prompt, user_id="u1", user_name="Tom", people=ps, speakers={"u1": "Tom"})
    assert 'answer exactly "Your form of address is Tom, and your name is Tom."' in text
    assert "### Tom [current speaker]" in text
    assert "Tom (Tom)" not in text
    assert " - Ann (Aunt)\n - Tom" in person(prompt, people=ps)


def _private_people(prompt):
    return [
        P(prompt, "u1", "James", "Dad", ("calendar.james", "James")),
        prompt.Person(
            "u2",
            "Sarah",
            "Mum",
            (("calendar.home", "Home"), ("calendar.diary", "Diary")),
            frozenset({"calendar.diary"}),
        ),
    ]


def test_other_peoples_private_entities_are_left_out(prompt):
    text = person(prompt, user_id="u1", user_name="James", people=_private_people(prompt))
    assert " - calendar.home: Home" in text
    assert "calendar.diary" not in text


def test_own_private_entities_are_marked(prompt):
    text = person(prompt, user_id="u2", user_name="Sarah", people=_private_people(prompt))
    assert " - calendar.diary: Diary (private)" in text
    assert " - calendar.home: Home\n" in text + "\n"


def test_person_with_only_private_entities_shows_none_to_others(prompt):
    ps = [
        P(prompt, "u1", "James", "Dad"),
        prompt.Person("u2", "Sarah", "Mum", (("calendar.diary", "Diary"),), frozenset({"calendar.diary"})),
    ]
    text = person(prompt, user_id="u1", user_name="James", people=ps)
    assert "### Sarah (Mum)\n(no entities)" in text
    assert "calendar.diary" not in text


def test_prompt_names_the_tools(prompt):
    text = person(prompt, user_id="u1", user_name="James", people=_private_people(prompt))
    for name in (
        "get_entity_state",
        "control_assigned_entity",
        "get_calendar_events",
        "search_calendar_events",
        "check_calendar_availability",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
        "get_person_location",
        "get_person_location_history",
    ):
        assert name in text


def test_group_headings_never_follow_a_list_item_directly(prompt):
    """A markdown renderer folds a line straight after a bullet into that bullet."""
    ents = (
        ("calendar.a", "A"),
        ("device_tracker.b", "B"),
        ("light.c", "C"),
    )
    text = person(
        prompt,
        user_id="u1",
        people=[P(prompt, "u1", "James", "Dad", *ents), P(prompt, "u2", "Sarah", "Mum")],
    )
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line in ("Devices:", "Other:"):
            assert lines[i - 1] == "", f"{line} needs a blank line above it"
    assert "A\n\nDevices:\n - device_tracker.b: B\n\nOther:\n - light.c: C" in text


def test_device_area_makes_here_and_this_room_resolve(prompt):
    text = prompt.build_device_prompt(
        device_id="abc123", device_name="Kitchen", area_name="Lounge"
    )
    assert "id abc123 (Kitchen)" in text
    assert 'The device is in the Lounge area, so "here" and "this room" mean the Lounge.' in text


def test_device_without_area_says_nothing_about_it(prompt):
    text = prompt.build_device_prompt(device_id="abc123", device_name="Kitchen")
    assert "area" not in text
    text = prompt.build_device_prompt(device_id=None, device_name=None, area_name="Lounge")
    assert "area" not in text and "is not known" in text
