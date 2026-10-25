# Speaker Recognition Tools

Tell your Home Assistant conversation agent who is speaking and which device they are speaking through, without hard-coding either into the main prompt.

> **Requirement:** this integration needs the **[Speaker Recognition](https://github.com/conorod1992/speaker-recognition)** project (its Docker server and its Home Assistant integration) already installed, set up and trained. Speaker Recognition identifies the voice and sets the Home Assistant user for each request. This integration only reads that result. Without Speaker Recognition, every speaker is treated as unknown.

> **WARNING: assigning an entity to a person bypasses Assist's exposed-entities setting.**
>
> Every entity you assign here is given to your conversation agent, and to the model behind it (which may be a cloud service), **whether or not you have exposed it to Assist**. Its id and name go into the prompt, and the tools can read it and, for calendars, write to it. Only assign entities you are happy to share with the agent.
>
> When someone is away, outside every zone, the location tool also gives their **street name and town** if their phone reports an address, so assigning a phone shares roughly where its owner is. Marking the person's tracker or the phone's geocoded location sensor private stops this for everyone but the owner.
>
> **Private** only limits which household member can use an entity through this integration. Other people's private entities are left out of their prompts and refused by the tools, but the owner's prompt still lists them, and any other tool that can see the entity is not restricted. To keep an entity away from those, do not expose it to Assist.

## What it adds

Two separate LLM APIs, added one at a time under Settings > Devices & Services > Add Integration. Each can be added once. Speaking Device only adds text to the agent's system prompt. Speaking Person adds text and, for recognised speakers only, three tools (see [Tools](#tools)).

### Speaking Person

Gives the agent the speaker's title.

- Add each person as a line under the entry: assign a Home Assistant user account to a title (for example James to Dad, Sarah to Mum). The title is optional; if you leave it blank, the first name on the account is used. Speaker Recognition links voice profiles to user accounts, not person entities, so pick the account its voice profile is linked to.
- Optionally assign entities to each person, such as their calendars and their phone from the Home Assistant Companion App. The agent uses them to answer "What's on my calendar on Thursday?", "What is Sarah doing on Friday afternoon?" or "Create an appointment on Sarah's and my calendars". The prompt lists an ENTITY MAPPINGS section with one block per person, and the agent is told to refer to people by title.
- Optionally mark some of a person's entities as **private**. A private entity can only be used by its owner: the tools refuse anyone else, and other people's private entities are left out of the prompt. Private entities must also be in the person's entity list.
- Unknown speakers get a title of your choice (default Unknown Person).
- **Deny unknown speakers** (off by default). When on, only the listed accounts can interact. Anyone else, including a request with no user, is refused with one of your refusal lines, one per row. This is an instruction to the agent, not a security barrier.

Each person you add appears as a line under Speaking Person on the integration page (use Add person, then the line's menu to change the title or delete it). The settings (gear icon) cover the unknown title, Deny unknown speakers and the refusal lines.

### Speaking Device

Gives the agent the id and name of the device the speaker is using, so tools that need to know which device is addressing the agent can use it.

## What gets added to the prompt

Four sections are appended to the conversation agent's system prompt. Speaking Person adds the first three, and Speaking Device adds the last. Which of them appears depends on who is speaking.

| Section | Added by | Shown to | What it does |
| --- | --- | --- | --- |
| `SPEAKING PERSON` | Speaking Person | Everyone | Says who is speaking. For a recognised speaker it gives their title and the name to answer with when they ask who they are, and tells the agent to refer to them only by title and to replace `[title]` with it. For an unidentified speaker it gives the unknown title and tells the agent to carry on as normal without claiming to know them. With Deny unknown speakers on, an unidentified speaker instead gets a lockdown instruction that overrides the rest of the prompt and makes the agent refuse with one of your refusal lines. |
| `ENTITY MAPPINGS` | Speaking Person | Recognised speakers | One block per configured person, with the speaker first and everyone else alphabetically. Each block lists that person's entities, grouped as Calendars, Devices and Other. Other people's private entities are left out, and the speaker's own private ones are marked `(private)`. It tells the agent that "my", "me" and "I" mean the current speaker, that a request about another person uses only that person's entities, that a request naming several people uses each person's matching entities, to ask which one when a person has several of the type needed, and to say so when a person has none. It also names the tools below. Left out when there is nobody else configured and the speaker has no entities. |
| `PEOPLE` | Speaking Person | Unidentified speakers who are allowed in | A list of the configured people and their titles, with no entities, so the agent can still refer to household members by title. Never shown with Deny unknown speakers on. |
| `SPEAKING DEVICE` | Speaking Device | Everyone | Gives the id, name and area of the device the request came through, so a tool that asks which device is addressing the agent can use it, and "here" and "this room" mean that area (for example the Lounge). The area is left out when the device has none. When the device is not known it says so and tells the agent to ask the speaker. |

Only first names are ever used, never a full account name. A person with no title is shown by their first name.

## Tools

Speaking Person gives recognised speakers three tools. Unidentified speakers, and speakers who are refused by Deny unknown speakers, get none.

| Tool | What it does |
| --- | --- |
| `get_calendar_events` | Reads the events on one or more people's calendars between a start and an end. `people` takes titles, names or "me" (default: the speaker). A date-only end covers that whole day. |
| `create_calendar_event` | Creates one event on one or more people's calendars, for example "on Sarah's and my calendars". The default length is one hour, and a date with no time makes an all-day event. Nothing is created unless every named person's calendar can be used. |
| `get_person_location` | Says where people are, using the `person` and `device_tracker` entities assigned to them. When someone is away, outside every zone, it also gives the street name and town if their phone or tracker reports an address (never the number, postcode or country). Each result also says how long they have been there, ready to say aloud, such as "home since three o'clock" or "away since eight o'clock this morning". Leave `people` out to see everyone, which answers "who is home?". |

If a person has more than one calendar and the request does not say which, the tool returns the choices and the agent asks the speaker, then calls the tool again with the chosen `entity_id`.

**Privacy.** The tools enforce it, not just the prompt. A private entity can be read or written only by its owner. If someone else asks for it, the tool says it is private, and a person with one private and one shared calendar looks like they have only the shared one. Entities that are not private are open to every recognised speaker.

**What this does not protect.** The rule only applies to this integration's tools and prompt text. Other tools the agent has, such as Home Assistant's own calendar tool or device controls, can still reach any entity exposed to your conversation agent. To keep an entity out of reach of them, do not expose it to Assist. The tools use the entities you assign here, whether or not they are exposed to Assist.

**How long.** The time comes from when the person entity (or the tracker that gave the location) last changed state. Home Assistant resets that when it restarts, so straight after a restart it can say someone has been home only since then. Times are spoken without am or pm, with "this morning", "yesterday evening" or the weekday added when it would otherwise be unclear, and a date for anything older than a week.

**Street addresses.** If the person's location is not a zone, the location tool looks for an address in this order: an `address`, `geocoded_location` or `formatted_address` attribute on the device tracker, then the Companion App's *Geocoded Location* sensor on the same device. The tool reduces it to street name and town, using the sensor's `Thoroughfare` and `Locality` attributes when present and otherwise the first line or two of the address. That sensor is found through the phone's device, so it does not need to be assigned to the person. Turn that sensor on in the Companion App's settings. If someone has marked the sensor private, only its owner gets the address.

Not every phone has geocoding turned on, and many trackers never report an address. When someone is away and no address is found, the tool tells the agent to reply with exactly "Sorry [speaker's title], An exact address for [person's title] is unknown." ("for you" when someone asks about themselves) and to add nothing else, so it does not guess. The wording lives in the tool, so you do not need to cover it in your prompt. It is an instruction to the model, which will normally follow it, but it is not enforced. Each person is checked on their own: one phone can give an address while another gives none.

The tools are written against Home Assistant 2026.10 and have only been tested there.

## Use it

1. Install and train Speaker Recognition first, and make sure your voice pipeline uses its wrapped speech-to-text and conversation entities.
2. Copy `custom_components/speaker_recognition_tools` into your Home Assistant `custom_components` folder and restart.
3. Add the integration once for each entry you want and configure Speaking Person.
4. In your conversation agent's settings, tick the new APIs under the LLM APIs list. Put them last in the list, so the static tool text stays first and prompt caching keeps working.
5. Add a paragraph like this to your conversation agent's own prompt, so the agent knows to trust the injected sections:

   > The user is whoever is speaking. Who they are, their title, the device they are speaking through, and the people and entities of this household are set in the SPEAKING PERSON, SPEAKING DEVICE, ENTITY MAPPINGS and PEOPLE sections added to this prompt. Those sections are authoritative. Never guess who is speaking.

   [`EXAMPLE_PROMPT.txt`](EXAMPLE_PROMPT.txt) is a complete example prompt for a generic home assistant that works with these sections. Use it as a starting point.

6. Where your prompt shows examples of the speaker's title, write `[title]`. The injected text tells the agent to replace it with the current speaker's title.

## Notes

- The text is plain, not Jinja, and Home Assistant wraps each API's text as "Follow these instructions for tools from ...".
- Recognition is reliable but not infallible. A misrecognised voice is treated as unknown, which with Deny unknown speakers on means a refusal.

## Licence

MIT
