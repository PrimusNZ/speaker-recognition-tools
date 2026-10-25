# Speaker Recognition Tools

Tell your Home Assistant conversation agent who is speaking and which device they are speaking through, without hard-coding either into the main prompt.

> **Requirement:** this integration needs the **[Speaker Recognition](https://github.com/conorod1992/speaker-recognition)** project (its Docker server and its Home Assistant integration) already installed, set up and trained. Speaker Recognition identifies the voice and sets the Home Assistant user for each request. This integration only reads that result. Without Speaker Recognition, every speaker is treated as unknown.

## What it adds

Two separate LLM APIs, added one at a time under Settings > Devices & Services > Add Integration. Each can be added once. Neither provides any tools; each only adds text to the agent's system prompt.

### Speaking Person

Gives the agent the speaker's title.

- Add each person as a line under the entry: assign a Home Assistant user account to a title (for example James to Dad, Sarah to Mum). The title is optional; if you leave it blank, the first name on the account is used. Speaker Recognition links voice profiles to user accounts, not person entities, so pick the account its voice profile is linked to.
- Optionally assign entities to each person, such as their calendars and their phone from the Home Assistant Companion App. The agent uses them to answer "What's on my calendar on Thursday?", "What is Sarah doing on Friday afternoon?" or "Create an appointment on Sarah's and my calendars". The prompt lists an ENTITY MAPPINGS section with one block per person, and the agent is told to refer to people by title.
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
| `ENTITY MAPPINGS` | Speaking Person | Recognised speakers | One block per configured person, with the speaker first and everyone else alphabetically. Each block lists that person's entities, grouped as Calendars, Devices and Other. It tells the agent that "my", "me" and "I" mean the current speaker, that a request about another person uses only that person's entities, that a request naming several people uses each person's matching entities, to ask which one when a person has several of the type needed, and to say so when a person has none. Left out when there is nobody else configured and the speaker has no entities. |
| `PEOPLE` | Speaking Person | Unidentified speakers who are allowed in | A list of the configured people and their titles, with no entities, so the agent can still refer to household members by title. Never shown with Deny unknown speakers on. |
| `SPEAKING DEVICE` | Speaking Device | Everyone | Gives the id and name of the device the request came through, so a tool that asks which device is addressing the agent can use it, or "here" can be resolved. When the device is not known it says so and tells the agent to ask the speaker. |

Only first names are ever used, never a full account name. A person with no title is shown by their first name.

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
