# Speaker Recognition Tools

Tell your Home Assistant conversation agent who is speaking and which device they are speaking through, without hard-coding either into the main prompt.

> **Requirement:** this integration needs the **[Speaker Recognition](https://github.com/conorod1992/speaker-recognition)** project (its Docker server and its Home Assistant integration) already installed, set up and trained. Speaker Recognition identifies the voice and sets the Home Assistant user for each request. This integration only reads that result. Without Speaker Recognition, every speaker is treated as unknown.

> **WARNING: assigning an entity to a person bypasses Assist's exposed-entities setting.**
>
> Every entity assigned to a person, including entities in a linked device, is given to your conversation agent and the model behind it (which may be a cloud service), **whether or not you have exposed it to Assist**. Its ID and configured name go into the prompt, and the tools can read its state and attributes or call a Home Assistant service on it. Calendar changes use a separate preview and confirmation flow. Only assign entities you are happy to share with the agent.
>
> When someone is outside every zone, the location tool uses their **street name and town** as their location if their phone reports an address, so assigning a phone shares roughly where its owner is. Marking the person's tracker or the phone's geocoded location sensor private stops this for everyone but the owner.
>
> Messages sent with `send_message_to_person` leave the house: they go to the person's phone through the notify action or notify entities you set for them.
>
> **Private** only limits which household member can use an entity through this integration. Other people's private entities are left out of their prompts and refused by the tools, but the owner's prompt still lists them, and any other tool that can see the entity is not restricted. To keep an entity away from those, do not expose it to Assist.

## What it adds

Two separate LLM APIs, added one at a time under Settings > Devices & Services > Add Integration. Each can be added once. Speaking Device only adds text to the agent's system prompt. Speaking Person adds text, a **Last speaker** sensor and, for recognised speakers only, fifteen tools (see [Tools](#tools)).

### Speaking Person

Gives the agent the speaker's identity and direct-address form. Direct address uses **Address as** or, when it is blank, the person's first name; the third-person reference is never used for direct address. Identity answers include the configured third-person reference, configured address form and name as applicable. Each person can also have an optional **Third-person reference** (for example, `The father`) for tool results and other mentions where the agent is talking about them rather than addressing them directly. This applies to tool results about the current speaker too.

- Add each person as a line under the entry: assign a Home Assistant user account and optionally set **Address as** (for example, James may be addressed as Dad). If it is blank, the first name on the account is used. Set **Third-person reference** if the agent should use a different form in tool results and when speaking about them rather than addressing them directly (for example, `The father`). Speaker Recognition links voice profiles to user accounts, not person entities, so pick the account its voice profile is linked to.
- Optionally assign entities to each person, such as their calendars and their phone from the Home Assistant Companion App. The agent uses them to answer "What's on my calendar on Thursday?", "What is Sarah doing on Friday afternoon?" or "Create an appointment on Sarah's and my calendars". You can give an assigned entity one or more aliases using one line per entity in the format `entity_id: alias, another alias`. The first alias becomes the entity's preferred name in prompt mappings and tool results; subsequent aliases remain alternate names. Calendar tools also accept any alias when asking which calendar to use. The prompt lists an ENTITY MAPPINGS section with one block per person. People may be identified by first name, configured address form or third-person reference; direct address uses the configured address form or, when blank, the first name.
- To refer to one device by the same name for status and control, add a **Linked device** under Speaking Person. Choose its person, spoken name, optional aliases, status entity and action entity. For example, a made-up `Demo unit` link with aliases `Lab station, Test console` can use `binary_sensor.demo_unit_status` for status and `button.demo_unit_action` for actions. The agent uses the spoken name or any alias for both questions and commands, routing status requests to the status entity and action requests to the action entity. The spoken name remains the preferred name in tool results. In the prompt, the linked name has nested **Aliases**, **Status entity**, and **Action entity** lines. Enable **Private to this person** to restrict both linked entities to that person's tools. Enable **Actions need confirmation** or **Actions are for administrators only** to apply those rules to the action entity.
- Optionally mark some of a person's entities as **private**. A private entity can only be used by its owner: the tools refuse anyone else, and other people's private entities are left out of the prompt. Private entities must also be in the person's entity list.
- Optionally list **Entities that need confirmation**. Any action on them needs a spoken yes first (see [Confirmations and administrator-only entities](#confirmations-and-administrator-only-entities)). Locks, alarm panels, and door, gate and garage door covers always need one.
- Optionally list **Administrator-only entities**. Only speakers whose Home Assistant account is an administrator can control them; anyone can still read their state.
- Optionally set a **Message action**, such as the Companion App's `notify.mobile_app_` action for their phone, so the agent can send them a message. Notify entities in their entity list are used too.
- Assign a person's own **to-do lists** (`todo` entities) to let the agent read and change them. Leave a household list, such as a shared shopping list, unassigned; Home Assistant's own tools still cover it.
- Unknown speakers get an **Address as** value of your choice (default Unknown Person).
- **Deny unknown speakers** (off by default). When on, only the listed accounts can interact. Anyone else, including a request with no user, is refused with one of your refusal lines, one per row. This is an instruction to the agent, not a security barrier.

Each person you add appears as a line under Speaking Person on the integration page (use Add person, then the line's menu to change their configured address form or delete them). The settings (gear icon) cover the unknown speaker's configured address form, Deny unknown speakers, the refusal lines and the **Minimum recognition confidence for changes** (see [Recognition confidence](#recognition-confidence)). **Preview prompt** lets you choose a configured person or Unknown speaker.

**Preview full prompt** is an integration-level action in the integration page's top action bar, next to **Add person**. It works even when no person has been added. The initial Add Integration menu also offers the preview before either API has been added. The preview includes only sections for configured APIs: if Speaking Person is configured but no people are added, it shows the unknown-speaker section as the live API does; it includes Speaking Device only when that API is configured. When the flow does not expose the signed-in account ID, it uses the Home Assistant owner account. The sample Speaking Device is selected only from devices with an enabled Assist satellite entity; if none exist, the device is shown as unknown. Prompt previews render the prompt's Markdown directly without a shaded box. In the full preview, the device disclaimer appears first, followed by a horizontal rule, the prompt, another horizontal rule, and the notes. Home Assistant sends only APIs selected for a conversation agent, and their order depends on the order they were added. The preview does not include the conversation agent's own prompt or Home Assistant's wrapper text.

### Speaking Device

Gives the agent the id and name of the device the speaker is using, so tools that need to know which device is addressing the agent can use it.

## What gets added to the prompt

Four sections are appended to the conversation agent's system prompt. Speaking Person adds the first three, and Speaking Device adds the last. Which of them appears depends on who is speaking.

| Section           | Added by        | Shown to                                 | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------------- | --------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SPEAKING PERSON` | Speaking Person | Everyone                                 | Says who is speaking. For a recognised speaker it gives their direct-address form and third-person reference, plus the identity answer to use if asked who they are. The answer includes whichever fields are configured: third-person reference and configured address form, configured address form only, third-person reference only, or name only. It also tells the agent to replace `[direct address]` with the direct-address form and to retain third-person references in tool results, including results about the current speaker. For an unidentified speaker it gives the unknown speaker's configured address form and tells the agent to carry on as normal without claiming to know them. With Deny unknown speakers on, an unidentified speaker instead gets a lockdown instruction that overrides the rest of the prompt and makes the agent refuse with one of your refusal lines.                                                                                                                                                     |
| `ENTITY MAPPINGS` | Speaking Person | Recognised speakers                      | One block per configured person, in alphabetical order. Each block lists that person's name, configured address form, optional third-person reference, and Home Assistant user level (`User` or `Administrator`), plus entities grouped as Calendars, To-do lists, Devices and Other. Entity aliases are shown beside the entity and can identify it; calendar tools accept an exact entity ID or alias when a choice is needed. Treat each person's first name, configured address form and configured reference as ways to identify the same person. Other people's private entities and aliases are left out. It tells the agent that "my", "me" and "I" mean the current speaker, that a request about another person uses only that person's entities, that a request naming several people uses each person's matching entities, to ask which one when a person has several of the type needed, and to say so when a person has none. It also names the tools below. Left out when there is nobody else configured and the speaker has no entities. |
| `PEOPLE`          | Speaking Person | Unidentified speakers who are allowed in | A list of configured people's names, configured address forms and third-person references, with no entities, so the agent can identify household members by any of those forms. Direct address uses the configured address form or, if absent, the first name; third-person references fall back from configured reference to configured address form to first name. Never shown with Deny unknown speakers on.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `SPEAKING DEVICE` | Speaking Device | Everyone                                 | Gives the id, name and area of the device the request came through, so a tool that asks which device is addressing the agent can use it, and "here" and "this room" mean that area (for example the Lounge). The area is left out when the device has none. When the device is not known it says so and tells the agent to ask the speaker.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

Only first names are ever used, never a full account name. Direct address always uses the configured address form, falling back to the person's first name if it is blank; a third-person reference is never used to address them directly. Third-person references use the configured reference, falling back to the configured address form and then the first name.

## Prompt caching

This integration adds information that can change from one request to the next, such as the recognised speaker and the device in use. Prompt caching can still reuse an identical prefix before that changing content; it does not require the entire prompt to stay identical.

For the best chance of cache reuse, keep the conversation prompt's opening and shared tool instructions stable, and put changing or person-specific content at the end. Home Assistant appends selected APIs after the conversation prompt, at the bottom, in the order they were added to the agent. Add APIs with static prompt or tool instructions before Speaking Device and Speaking Person. Keep the selected model and tool definitions stable where possible. Speaking Person offers its tools only to recognised speakers, so requests with different available tools may not share the same cached prefix.

The stable prefix also needs to meet the minimum length supported by the provider and model. That threshold varies; 1,024 tokens is common, but check the provider's documentation for the model in use. Cache lifetime and reuse also vary, so this arrangement improves the chance of a cache hit but cannot guarantee one.

## Tools

Speaking Person gives recognised speakers fifteen tools. Unidentified speakers, and speakers who are refused by Deny unknown speakers, get none.

For tools with a `people` or `person` parameter, identify people by first name, configured address form, or configured third-person reference; these forms refer to the same person. Use `me` for the current speaker. The default when the parameter is omitted depends on the tool.

| Tool                          | What it does                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_entity_state`            | Reads the current state and attributes of one entity assigned to a person, including its configured Home Assistant area when available. Accepts an entity ID, configured name or alias; the first alias is the preferred name.                                                                                                                                                                                                                                                                                                                                                                                          |
| `control_assigned_entity`     | Calls a Home Assistant service on one entity assigned to a person, such as `switch.turn_on` or `climate.set_temperature`. The target is restricted to that single assigned entity; calendar changes must use the preview and confirmation tools below. Some actions need a preview and a yes first, and administrator-only entities refuse other speakers.                                                                                                                                                                                                                                                              |
| `get_calendar_events`         | Reads the events on one or more people's calendars between a start and an end. `people` accepts first names, configured address forms, or configured third-person references; "me" means the current speaker, and omitting `people` defaults to the speaker. A date-only end covers that whole day.                                                                                                                                                                                                                                                                                                                     |
| `search_calendar_events`      | Finds calendar events by title within a date range and returns event IDs for later updates or deletion.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `check_calendar_availability` | Checks whether a time range overlaps events on one or more assigned calendars.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `create_calendar_event`       | Previews an event on one or more people's calendars, for example "on Sarah's and my calendars". The default length is one hour, and a date with no time makes an all-day event. Nothing changes until the speaker explicitly agrees and the tool is called again with the confirmation token.                                                                                                                                                                                                                                                                                                                           |
| `update_calendar_event`       | Previews a change to one event, then updates it only after the speaker explicitly agrees. Its optional `person` accepts a first name, configured address form, or configured third-person reference; omitting it selects the speaker. Requires a calendar that supports event updates.                                                                                                                                                                                                                                                                                                                                  |
| `delete_calendar_event`       | Previews an event deletion, then deletes it only after the speaker explicitly agrees. Its optional `person` accepts a first name, configured address form, or configured third-person reference; omitting it selects the speaker. Requires a calendar that supports event deletion.                                                                                                                                                                                                                                                                                                                                     |
| `get_person_location`         | Says where people are, using the `person` and `device_tracker` entities assigned to them. When someone is outside every zone, it uses the street name and town as their location if their phone or tracker reports an address (never the number, postcode or country). Each result also says how long they have been at that location, ready to say aloud, such as "home since three o'clock" or "Example Road since eight o'clock this morning". If no address is available, it says the exact address is unknown rather than suggesting a location. Leave `people` out to see everyone, which answers "who is home?". |
| `get_person_location_history` | Shows recorded location changes for assigned person and tracker entities, including when someone arrived or left. The recorder must be enabled and retain the requested history; ranges are limited to 31 days.                                                                                                                                                                                                                                                                                                                                                                                                         |
| `get_todo_items`              | Reads the open (or completed) items on one or more people's assigned to-do lists. Omitting `people` defaults to the speaker.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `add_todo_item`               | Previews an item for one person's to-do list, with an optional due date and description, then adds it only after the speaker explicitly agrees.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `update_todo_item`            | Previews marking an item done or not done, renaming it or changing its due date, then makes the change only after the speaker explicitly agrees.                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `remove_todo_item`            | Previews removing an item, then removes it only after the speaker explicitly agrees.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `send_message_to_person`      | Previews a message to one or more people's phones, titled with who it is from, then sends it only after the speaker explicitly agrees. It sends to everyone named or to nobody.                                                                                                                                                                                                                                                                                                                                                                                                                                         |

If a person has more than one calendar and the request does not say which, the tool returns the choices and the agent asks the speaker, then calls the tool again with the chosen `entity_id`.

**Privacy.** The tools enforce it, not just the prompt. A private entity can be read or written only by its owner. If someone else asks for it, the tool says it is private, and a person with one private and one shared calendar looks like they have only the shared one. Entities that are not private are open to every recognised speaker.

The generic entity tools only access entities assigned to the selected person. They return the entity's state and attributes, or call a service targeted at that single entity. A linked device's shared name routes status requests to its status entity and action requests to its action entity. They do not guess a room from a `home` state, and they do not bypass the calendar confirmation flow.

**What this does not protect.** The rule only applies to this integration's tools and prompt text. Other tools the agent has, such as Home Assistant's own calendar tool or device controls, can still reach any entity exposed to your conversation agent. To keep an entity out of reach of them, do not expose it to Assist. The tools use the entities you assign here, whether or not they are exposed to Assist.

**How long.** The time comes from when the person entity (or the tracker that gave the location) last changed state. Home Assistant resets that when it restarts, so straight after a restart it can say someone has been home only since then. Times are spoken without am or pm, with "this morning", "yesterday evening" or the weekday added when it would otherwise be unclear, and a date for anything older than a week.

**Calendar changes.** Creating, updating and deleting an event always takes two calls. The first returns a preview and confirmation token without changing the calendar. The agent must ask the speaker and proceed only after an explicit yes; the second call must include the same request and token. A declined or expired preview makes no change. Update and delete are available only for calendar integrations that support those operations. This is an instruction and tool flow, not a guarantee that the model will follow it.

**To-do lists.** Only to-do lists assigned to a person are used, and private lists follow the same rules as private calendars. Adding, updating and removing items each take a preview and a yes, like calendar changes. The list must support the change; for example, some lists cannot set due dates.

**Messages.** `send_message_to_person` uses the person's **Message action** and any `notify` entities in their entity list. A private notify entity is used only when the owner sends themselves a message. If anyone named has no way to be reached, nothing is sent.

**Location history.** `get_person_location_history` reads state changes from Home Assistant Recorder for assigned, non-private person and tracker entities. Recorder must be enabled and retain the requested period. The tool returns zone or tracker states and timestamps, not address attributes.

**Street addresses.** If the person's location is not a zone, the location tool looks for an address in this order: an `address`, `geocoded_location` or `formatted_address` attribute on the device tracker, then the Companion App's _Geocoded Location_ sensor on the same device. The tool reduces it to street name and town, using the sensor's `Thoroughfare` and `Locality` attributes when present and otherwise the first line or two of the address. That sensor is found through the phone's device, so it does not need to be assigned to the person. Turn that sensor on in the Companion App's settings. If someone has marked the sensor private, only its owner gets the address.

Not every phone has geocoding turned on, and many trackers never report an address. When someone is outside every zone and no address is found, the tool tells the agent to reply with exactly "Sorry [speaker's configured address form or name], An exact address for [person's third-person reference, configured address form or name] is unknown." When the location request is about the current speaker, the exact reply says "for you" instead and uses the direct-address form in the salutation. The wording lives in the tool, so you do not need to cover it in your prompt. It is an instruction to the model, which will normally follow it, but it is not enforced. Each person is checked on their own: one phone can give an address while another gives none.

The integration needs Home Assistant 2026.10 or later, and HACS will not install it on older versions.

## Confirmations and administrator-only entities

Some device actions take two calls, like calendar changes: the first returns a preview and a confirmation token without changing anything, and the agent must ask the speaker and repeat the same request with the token after an explicit yes. This applies to:

- Locks, except locking.
- Alarm panels, except arming.
- Covers whose device class is door, gate or garage, except closing and stopping. Blinds, shades and other covers are not included.
- Any action on an entity in the person's **Entities that need confirmation** list, or on a linked device with **Actions need confirmation**.
- Any change through the tools when the turn's recognition confidence is low (see below).

A confirmation belongs to the speaker who asked for it and to that exact request, and lasts five minutes.

**Administrator-only entities** can be controlled only by speakers whose Home Assistant account is an administrator. Other speakers can still read the entity's state.

These rules are enforced by the tools, so the agent cannot skip them. The spoken yes, however, is something the model asks for and reports, not a voice check.

## Recognition confidence

Speaker Recognition sets only the Home Assistant user on each turn. It keeps the match score in its own decision history. When **Minimum recognition confidence for changes** is above 0, this integration reads the score for the current turn from that history. If the score is below the minimum, every change through the tools needs a preview and a yes, including device actions that normally run straight away, and the agent is asked to confirm who is speaking first.

That history is internal to Speaker Recognition and may change in any of its releases. When the score cannot be read, nothing changes from the behaviour without this setting. The diagnostics download shows whether the history can be read. Speaker Recognition's own minimum confidence still decides whether a voice is recognised at all.

## Last speaker sensor and event

Every Speaking Person turn updates the **Last speaker** sensor and fires a `speaker_recognition_tools_speaker` event, so automations can react to who spoke and where. The sensor's state is the speaker's first name, or `unknown_speaker`. The sensor attributes and event data include `user_id`, `address_as`, `device_id`, `device`, `area`, `confidence` (from Speaker Recognition, or `null` when not available), `uncertain` and `time`. The event data also has `recognised` and `name`. Typed chats in the Home Assistant app use the signed-in account, so they count as that person speaking.

```yaml
triggers:
  - trigger: event
    event_type: speaker_recognition_tools_speaker
    event_data:
      name: James
      area: Kitchen
actions:
  - action: light.turn_on
    target:
      area_id: kitchen
```

## Repairs and diagnostics

The integration keeps saved people in step with Home Assistant:

- Renamed entities are updated in every setting that refers to them, including aliases, private and confirmation lists, and linked devices.
- Entities that no longer exist, and missing message actions, raise a Repairs issue for that person or linked device. A registered entity that is only unavailable is not reported.
- A person whose user account was deleted, or has no name, raises a Repairs issue, because that voice is now treated as unknown.

Issues clear themselves once the settings are fixed. The diagnostics download (on the integration's menu) lists each person's setup without names, aliases or addresses, so it is safe to attach to an issue. It does include entity IDs.

## Actions for scripts

The integration adds one Home Assistant action that scripts, automations and templates can call.

**`speaker_recognition_tools.get_user_level`** returns a person's Home Assistant user level, so a script can allow or block something by level. It only returns a response, so call it with `response_variable`:

```yaml
- action: speaker_recognition_tools.get_user_level
  data:
    person: Dad
  response_variable: speaker
- if:
    - condition: template
      value_template: "{{ speaker.is_admin }}"
  then:
    - action: lock.unlock
      target:
        entity_id: lock.front_door
```

| Field     | What it does                                                                                                                                                 |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `person`  | A configured person's first name, address form or third-person reference.                                                                                    |
| `user_id` | A Home Assistant user ID. Used when no `person` is given. Giving both is an error.                                                                           |
| neither   | Uses the user who started the script. When the agent runs a script, Home Assistant normally passes the speaker's user through, but check this on your setup. |

The response has `found`, `is_admin`, `level` (`Administrator` or `User`, or `null` when not found), `configured`, `user_id`, `name` (first name only), `address_as` and, when nothing was found, `reason` (`unknown_person`, `ambiguous_person`, `unknown_user` or `no_user`).

- **Unknown is never an administrator.** An unknown or ambiguous person, an unknown user ID, or no user at all returns `found: false` and `is_admin: false`, so a script that checks `is_admin` fails safe.
- **Accounts that are not configured people** still get an answer when you look them up by `user_id` or by the user who started the script. They return their account's level and first name with `configured: false`. A `person` lookup only matches configured people.
- **`address_as` for anyone who is not a configured person** is the Speaking Person's unknown speaker address form (the **Address as** setting for unknown speakers, default `Unknown Person`), so a script can address them the same way the agent does. This covers unknown or ambiguous people, unknown users, no user, and accounts that are not configured people.
- Add `configured` to your check if the script should only trust people you have set up.

## Use it

1. Install and train Speaker Recognition first, and make sure your voice pipeline uses its wrapped speech-to-text and conversation entities.
2. Copy `custom_components/speaker_recognition_tools` into your Home Assistant `custom_components` folder and restart.
3. Add the integration once for each entry you want and configure Speaking Person.
4. In your conversation agent's settings, add the new APIs under the LLM APIs list after APIs with static prompt or tool instructions. Home Assistant appends them at the bottom in the order they were added, keeping changing speaker and device details after the stable prompt prefix. See [Prompt caching](#prompt-caching).
5. Add a paragraph like this to your conversation agent's own prompt, so the agent knows to trust the injected sections:

   > The user is whoever is speaking. Who they are, their configured address form or name for direct address, their third-person reference, the device they are speaking through, and the people and entities of this household are set in the SPEAKING PERSON, SPEAKING DEVICE, ENTITY MAPPINGS and PEOPLE sections added to this prompt. Those sections are authoritative. Never guess who is speaking.

   [`EXAMPLE_PROMPT.txt`](EXAMPLE_PROMPT.txt) is a complete example prompt for a generic home assistant that works with these sections. Use it as a starting point.

6. Where your prompt shows examples of the speaker's direct-address form, write `[direct address]`. The injected text replaces it with the current speaker's configured address form, or first name if none is set.

## Notes

- The text is plain, not Jinja, and Home Assistant wraps each API's text as "Follow these instructions for tools from ...".
- Recognition is reliable but not infallible. A misrecognised voice is treated as unknown, which with Deny unknown speakers on means a refusal.

## Licence

MIT
