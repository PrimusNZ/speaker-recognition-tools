# Speaker Recognition Tools

Tell your Home Assistant conversation agent who is speaking and which device they are speaking through, without hard-coding either into the main prompt.

> **Requirement:** this integration needs the **[Speaker Recognition](https://github.com/conorod1992/speaker-recognition)** project (its Docker server and its Home Assistant integration) already installed, set up and trained. Speaker Recognition identifies the voice and sets the Home Assistant user for each request. This integration only reads that result. Without Speaker Recognition, every speaker is treated as unknown.

> **WARNING: assigning an entity to a person bypasses Assist's exposed-entities setting.**
>
> Every entity you assign here is given to your conversation agent, and to the model behind it (which may be a cloud service), **whether or not you have exposed it to Assist**. Its id, name and configured aliases go into the prompt, and the tools can read its state and attributes or call a Home Assistant service on it. Calendar changes use a separate preview and confirmation flow. Only assign entities you are happy to share with the agent.
>
> When someone is outside every zone, the location tool uses their **street name and town** as their location if their phone reports an address, so assigning a phone shares roughly where its owner is. Marking the person's tracker or the phone's geocoded location sensor private stops this for everyone but the owner.
>
> **Private** only limits which household member can use an entity through this integration. Other people's private entities are left out of their prompts and refused by the tools, but the owner's prompt still lists them, and any other tool that can see the entity is not restricted. To keep an entity away from those, do not expose it to Assist.

## What it adds

Two separate LLM APIs, added one at a time under Settings > Devices & Services > Add Integration. Each can be added once. Speaking Device only adds text to the agent's system prompt. Speaking Person adds text and, for recognised speakers only, ten tools (see [Tools](#tools)).

### Speaking Person

Gives the agent the speaker's identity and direct-address form. Direct address uses **Address as** or, when it is blank, the person's first name; the third-person reference is never used for direct address. Identity answers include the configured third-person reference, configured address form and name as applicable. Each person can also have an optional **Third-person reference** (for example, `The father`) for tool results and other mentions where the agent is talking about them rather than addressing them directly. This applies to tool results about the current speaker too.

- Add each person as a line under the entry: assign a Home Assistant user account and optionally set **Address as** (for example, James may be addressed as Dad). If it is blank, the first name on the account is used. Set **Third-person reference** if the agent should use a different form in tool results and when speaking about them rather than addressing them directly (for example, `The father`). Speaker Recognition links voice profiles to user accounts, not person entities, so pick the account its voice profile is linked to.
- Optionally assign entities to each person, such as their calendars and their phone from the Home Assistant Companion App. The agent uses them to answer "What's on my calendar on Thursday?", "What is Sarah doing on Friday afternoon?" or "Create an appointment on Sarah's and my calendars". You can give an assigned entity one or more aliases using one line per entity in the format `entity_id: alias, another alias`. The first alias becomes the entity's preferred name in prompt mappings and tool results; subsequent aliases remain alternate names. Calendar tools also accept any alias when asking which calendar to use. The prompt lists an ENTITY MAPPINGS section with one block per person. People may be identified by first name, configured address form or third-person reference; direct address uses the configured address form or, when blank, the first name.
- Optionally mark some of a person's entities as **private**. A private entity can only be used by its owner: the tools refuse anyone else, and other people's private entities are left out of the prompt. Private entities must also be in the person's entity list.
- Unknown speakers get an **Address as** value of your choice (default Unknown Person).
- **Deny unknown speakers** (off by default). When on, only the listed accounts can interact. Anyone else, including a request with no user, is refused with one of your refusal lines, one per row. This is an instruction to the agent, not a security barrier.

Each person you add appears as a line under Speaking Person on the integration page (use Add person, then the line's menu to change their configured address form or delete them). The settings (gear icon) cover the unknown speaker's configured address form, Deny unknown speakers and the refusal lines. **Preview prompt** lets you choose a configured person or Unknown speaker.

**Preview full prompt** is an integration-level action in the integration page's top action bar, next to **Add person**. It works even when no person has been added. The initial Add Integration menu also offers the preview before either API has been added. The preview includes only sections for configured APIs: if Speaking Person is configured but no people are added, it shows the unknown-speaker section as the live API does; it includes Speaking Device only when that API is configured. When the flow does not expose the signed-in account ID, it uses the Home Assistant owner account. The sample Speaking Device is selected only from devices with an enabled Assist satellite entity; if none exist, the device is shown as unknown. When Speaking Device is configured, a disclaimer appears first, followed by a **Prompt Preview:** label and a shaded, wrapping prompt box. Home Assistant sends only APIs selected for a conversation agent, and their order depends on the order they were added. The preview does not include the conversation agent's own prompt or Home Assistant's wrapper text.

### Speaking Device

Gives the agent the id and name of the device the speaker is using, so tools that need to know which device is addressing the agent can use it.

## What gets added to the prompt

Four sections are appended to the conversation agent's system prompt. Speaking Person adds the first three, and Speaking Device adds the last. Which of them appears depends on who is speaking.

| Section | Added by | Shown to | What it does |
| --- | --- | --- | --- |
| `SPEAKING PERSON` | Speaking Person | Everyone | Says who is speaking. For a recognised speaker it gives their direct-address form and third-person reference, plus the identity answer to use if asked who they are. The answer includes whichever fields are configured: third-person reference and configured address form, configured address form only, third-person reference only, or name only. It also tells the agent to replace `[direct address]` with the direct-address form and to retain third-person references in tool results, including results about the current speaker. For an unidentified speaker it gives the unknown speaker's configured address form and tells the agent to carry on as normal without claiming to know them. With Deny unknown speakers on, an unidentified speaker instead gets a lockdown instruction that overrides the rest of the prompt and makes the agent refuse with one of your refusal lines. |
| `ENTITY MAPPINGS` | Speaking Person | Recognised speakers | One block per configured person, with the speaker first and everyone else alphabetically. Each block lists that person's name, configured address form and optional third-person reference, plus entities grouped as Calendars, Devices and Other. Entity aliases are shown beside the entity and can identify it; calendar tools accept an exact entity ID or alias when a choice is needed. Treat each person's first name, configured address form and configured reference as ways to identify the same person. Other people's private entities and aliases are left out, and the speaker's own private ones are marked `(private)`. It tells the agent that "my", "me" and "I" mean the current speaker, that a request about another person uses only that person's entities, that a request naming several people uses each person's matching entities, to ask which one when a person has several of the type needed, and to say so when a person has none. It also names the tools below. Left out when there is nobody else configured and the speaker has no entities. |
| `PEOPLE` | Speaking Person | Unidentified speakers who are allowed in | A list of configured people's names, configured address forms and third-person references, with no entities, so the agent can identify household members by any of those forms. Direct address uses the configured address form or, if absent, the first name; third-person references fall back from configured reference to configured address form to first name. Never shown with Deny unknown speakers on. |
| `SPEAKING DEVICE` | Speaking Device | Everyone | Gives the id, name and area of the device the request came through, so a tool that asks which device is addressing the agent can use it, and "here" and "this room" mean that area (for example the Lounge). The area is left out when the device has none. When the device is not known it says so and tells the agent to ask the speaker. |

Only first names are ever used, never a full account name. Direct address always uses the configured address form, falling back to the person's first name if it is blank; a third-person reference is never used to address them directly. Third-person references use the configured reference, falling back to the configured address form and then the first name.

## Prompt caching

This integration adds information that can change from one request to the next, such as the recognised speaker and the device in use. Prompt caching can still reuse an identical prefix before that changing content; it does not require the entire prompt to stay identical.

For the best chance of cache reuse, keep the conversation prompt's opening and shared tool instructions stable, and put changing or person-specific content at the end. Home Assistant appends selected APIs after the conversation prompt, at the bottom, in the order they were added to the agent. Add APIs with static prompt or tool instructions before Speaking Device and Speaking Person. Keep the selected model and tool definitions stable where possible. Speaking Person offers its tools only to recognised speakers, so requests with different available tools may not share the same cached prefix.

The stable prefix also needs to meet the minimum length supported by the provider and model. That threshold varies; 1,024 tokens is common, but check the provider's documentation for the model in use. Cache lifetime and reuse also vary, so this arrangement improves the chance of a cache hit but cannot guarantee one.

## Tools

Speaking Person gives recognised speakers ten tools. Unidentified speakers, and speakers who are refused by Deny unknown speakers, get none.

For tools with a `people` or `person` parameter, identify people by first name, configured address form, or configured third-person reference; these forms refer to the same person. Use `me` for the current speaker. The default when the parameter is omitted depends on the tool.

| Tool | What it does |
| --- | --- |
| `get_entity_state` | Reads the current state and attributes of one entity assigned to a person, including its configured Home Assistant area when available. Accepts an entity ID, configured name or alias; the first alias is the preferred name. Use it for questions such as a car's fuel sensor. |
| `control_assigned_entity` | Calls a Home Assistant service on one entity assigned to a person, such as `switch.turn_on` or `climate.set_temperature`. The target is restricted to that single assigned entity; calendar changes must use the preview and confirmation tools below. |
| `get_calendar_events` | Reads the events on one or more people's calendars between a start and an end. `people` accepts first names, configured address forms, or configured third-person references; "me" means the current speaker, and omitting `people` defaults to the speaker. A date-only end covers that whole day. |
| `search_calendar_events` | Finds calendar events by title within a date range and returns event IDs for later updates or deletion. |
| `check_calendar_availability` | Checks whether a time range overlaps events on one or more assigned calendars. |
| `create_calendar_event` | Previews an event on one or more people's calendars, for example "on Sarah's and my calendars". The default length is one hour, and a date with no time makes an all-day event. Nothing changes until the speaker explicitly agrees and the tool is called again with the confirmation token. |
| `update_calendar_event` | Previews a change to one event, then updates it only after the speaker explicitly agrees. Its optional `person` accepts a first name, configured address form, or configured third-person reference; omitting it selects the speaker. Requires a calendar that supports event updates. |
| `delete_calendar_event` | Previews an event deletion, then deletes it only after the speaker explicitly agrees. Its optional `person` accepts a first name, configured address form, or configured third-person reference; omitting it selects the speaker. Requires a calendar that supports event deletion. |
| `get_person_location` | Says where people are, using the `person` and `device_tracker` entities assigned to them. When someone is outside every zone, it uses the street name and town as their location if their phone or tracker reports an address (never the number, postcode or country). Each result also says how long they have been at that location, ready to say aloud, such as "home since three o'clock" or "High Street since eight o'clock this morning". If no address is available, it says the exact address is unknown rather than suggesting a location. Leave `people` out to see everyone, which answers "who is home?". |
| `get_person_location_history` | Shows recorded location changes for assigned person and tracker entities, including when someone arrived or left. The recorder must be enabled and retain the requested history; ranges are limited to 31 days. |

If a person has more than one calendar and the request does not say which, the tool returns the choices and the agent asks the speaker, then calls the tool again with the chosen `entity_id`.

**Privacy.** The tools enforce it, not just the prompt. A private entity can be read or written only by its owner. If someone else asks for it, the tool says it is private, and a person with one private and one shared calendar looks like they have only the shared one. Entities that are not private are open to every recognised speaker.

The generic entity tools only access entities assigned to the selected person. They return the entity's state and attributes, or call a service targeted at that single entity. They do not guess a room from a `home` state, and they do not bypass the calendar confirmation flow.

**What this does not protect.** The rule only applies to this integration's tools and prompt text. Other tools the agent has, such as Home Assistant's own calendar tool or device controls, can still reach any entity exposed to your conversation agent. To keep an entity out of reach of them, do not expose it to Assist. The tools use the entities you assign here, whether or not they are exposed to Assist.

**How long.** The time comes from when the person entity (or the tracker that gave the location) last changed state. Home Assistant resets that when it restarts, so straight after a restart it can say someone has been home only since then. Times are spoken without am or pm, with "this morning", "yesterday evening" or the weekday added when it would otherwise be unclear, and a date for anything older than a week.

**Calendar changes.** Creating, updating and deleting an event always takes two calls. The first returns a preview and confirmation token without changing the calendar. The agent must ask the speaker and proceed only after an explicit yes; the second call must include the same request and token. A declined or expired preview makes no change. Update and delete are available only for calendar integrations that support those operations. This is an instruction and tool flow, not a guarantee that the model will follow it.

**Location history.** `get_person_location_history` reads state changes from Home Assistant Recorder for assigned, non-private person and tracker entities. Recorder must be enabled and retain the requested period. The tool returns zone or tracker states and timestamps, not address attributes.

**Street addresses.** If the person's location is not a zone, the location tool looks for an address in this order: an `address`, `geocoded_location` or `formatted_address` attribute on the device tracker, then the Companion App's *Geocoded Location* sensor on the same device. The tool reduces it to street name and town, using the sensor's `Thoroughfare` and `Locality` attributes when present and otherwise the first line or two of the address. That sensor is found through the phone's device, so it does not need to be assigned to the person. Turn that sensor on in the Companion App's settings. If someone has marked the sensor private, only its owner gets the address.

Not every phone has geocoding turned on, and many trackers never report an address. When someone is outside every zone and no address is found, the tool tells the agent to reply with exactly "Sorry [speaker's configured address form or name], An exact address for [person's third-person reference, configured address form or name] is unknown." When the location request is about the current speaker, the exact reply says "for you" instead and uses the direct-address form in the salutation. The wording lives in the tool, so you do not need to cover it in your prompt. It is an instruction to the model, which will normally follow it, but it is not enforced. Each person is checked on their own: one phone can give an address while another gives none.

The tools are written against Home Assistant 2026.10 and have only been tested there.

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
