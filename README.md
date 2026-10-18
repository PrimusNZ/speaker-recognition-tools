# Speaker Recognition Tools

Tell your Home Assistant conversation agent who is speaking and which device they are speaking through, without hard-coding either into the main prompt.

> **Requirement:** this integration needs the **[Speaker Recognition](https://github.com/conorod1992/speaker-recognition)** project (its Docker server and its Home Assistant integration) already installed, set up and trained. Speaker Recognition identifies the voice and sets the Home Assistant user for each request. This integration only reads that result. Without Speaker Recognition, every speaker is treated as unknown.

## What it adds

Two separate LLM APIs, added one at a time under Settings > Devices & Services > Add Integration. Each can be added once. Neither provides any tools; each only adds text to the agent's system prompt.

### Speaking Person

Gives the agent the speaker's title.

- Add each person as a line under the entry: assign a Home Assistant user account to a title (for example James to Dad, Sarah to Mum). Speaker Recognition links voice profiles to user accounts, not person entities, so pick the account its voice profile is linked to.
- Unknown speakers get a title of your choice (default Infiltrator).
- **Deny unknown speakers** (off by default). When on, only the listed accounts can interact. Anyone else, including a request with no user, is refused with one of your refusal lines, one per row. This is an instruction to the agent, not a security barrier.

Each person you add appears as a line under Speaking Person on the integration page (use Add person, then the line's menu to change the title or delete it). The settings (gear icon) cover the unknown title, Deny unknown speakers and the refusal lines.

### Speaking Device

Gives the agent the id and name of the device the speaker is using, so tools that need to know which device is addressing the agent can use it.

## Use it

1. Install and train Speaker Recognition first, and make sure your voice pipeline uses its wrapped speech-to-text and conversation entities.
2. Copy `custom_components/speaker_recognition_tools` into your Home Assistant `custom_components` folder and restart.
3. Add the integration once for each entry you want and configure Speaking Person.
4. In your conversation agent's settings, tick the new APIs under the LLM APIs list. Put them last in the list, so the static tool text stays first and prompt caching keeps working.
5. Where your prompt shows examples of the speaker's title, write `[title]`. The injected text tells the agent to replace it with the current speaker's title.

## Notes

- The text is plain, not Jinja, and Home Assistant wraps each API's text as "Follow these instructions for tools from ...".
- Recognition is reliable but not infallible. A misrecognised voice is treated as unknown, which with Deny unknown speakers on means a refusal.

## Licence

MIT
