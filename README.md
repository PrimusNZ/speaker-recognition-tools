# Speaker Recognition Tools

Tell your Home Assistant voice assistant who is speaking and which device they are speaking to, so it can answer "What's on my calendar?", "Where is my phone?" or "Add 'renew the car registration' to my to-do list" for the right person.

It adds two options for your conversation agent:

- **Speaking Person** tells the agent who is speaking, what to call them, and gives it a set of tools for their calendars, to-do list, location, devices and messages.
- **Speaking Device** tells the agent which device (and room) the request came from, so "here" and "this room" work.

> **Needs Speaker Recognition.** This integration reads the result of the **[Speaker Recognition](https://github.com/conorod1992/speaker-recognition)** project, which identifies the voice and sets the Home Assistant user for each request. Install and train that first. Without it, everyone is treated as unknown.

## Before you start

Please read this. The agent's model may be a cloud service, and these tools hand it real information about your home.

- **Anything you give a person is shared with the agent, whether or not you exposed it to Assist.** That covers their calendars, to-do list, other entities, their person entity and the phones and trackers linked to them. The agent can read it, and change it where a tool allows.
- **Location is shared too.** Someone's zone is shared, and when they are outside every zone, so is their street name and town if their phone reports one. Turn on **Location is private** for anyone who shouldn't be tracked by the rest of the household.
- **Messages leave the house.** "Tell Sarah dinner is ready" is sent to her phone.
- **"Private" only limits other household members** using this integration. Other tools your agent has can still see anything you expose to Assist.
- **Rules are instructions to the model, not locks.** The tools enforce who can see what, but things like "ask for a yes first" depend on the model following instructions. Privacy settings also can't take back anything the model was already told earlier in the same chat, so start a new chat after changing one.

## Set it up

1. Install it through HACS (add this repository as a custom repository if it isn't listed) and restart Home Assistant. You need Home Assistant 2026.10 or later.
2. Go to **Settings > Devices & services > Add integration**, add **Speaker Recognition Tools**, and choose **Speaking Person**. Do it again for **Speaking Device** if you want it.
3. In your conversation agent's settings, add the new APIs to the list of LLM APIs, after any APIs with fixed instructions.
4. Add this to your agent's own prompt so it trusts the added sections:

   ```text
   Who is speaking, what to call them, which device they are using, and which people and entities belong to this household are given to you in the SPEAKING PERSON, SPEAKING DEVICE, ENTITY MAPPINGS and PEOPLE sections added to this prompt.

   Treat those sections as correct. Never guess who is speaking.
   ```

## Add your people

Under Speaking Person, choose **Add person** and pick their **Person**. Only people linked to a Home Assistant user account are offered, because that's what Speaker Recognition identifies. Everything else is optional:

| Setting                         | What it does                                                                                                                  |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Location is private             | Hides this person's location from other people. They can still ask whether the person's devices are home, and which room.     |
| To-do list is private           | Hides this person's to-do list from other people.                                                                             |
| Address as                      | What the agent calls them, for example "Dad". If blank, their first name.                                                     |
| Third-person reference          | How the agent talks about them to others, for example "The breadwinner".                                                      |
| Entities, Entity aliases        | Other things that belong to them, such as a phone battery sensor. Aliases are other names for an entity, one line per entity. |
| To-do list                      | Their one to-do list. The agent calls it "your to-do list" or "Sarah's to-do list".                                           |
| Calendars                       | Their calendars. You can pick several.                                                                                        |
| Private entities                | Entities or calendars from the lists above that only they can use.                                                            |
| Entities that need confirmation | The agent must get a spoken yes before acting on these.                                                                       |
| Administrator-only entities     | Only Home Assistant administrators can control these.                                                                         |
| Message action                  | The notify action for their phone, so the agent can message them.                                                             |

Their phones and trackers come from the person in **Settings > People**, so you don't add those here.

A **Linked device** gives one spoken name to two entities, one for status and one for actions. For example, "the heater" can read `sensor.heater_status` and switch `switch.heater`. Add one under Speaking Person.

The settings (gear icon) cover how unknown speakers are addressed, **Deny unknown speakers** (refuse anyone who isn't recognised), the refusal lines, and **Minimum recognition confidence for changes**. **Preview prompt** shows exactly what the agent will be told for any person.

## What you can ask

- "What's on my calendar on Thursday?" or "What is Sarah doing on Friday afternoon?"
- "Add a meeting with Sam to my calendar on Tuesday at ten." The agent describes the change first and waits for your yes.
- "Add 'renew the car registration' to my to-do list" or "Mark washing the car as done."
- "Where is Sarah?", "Who is home?", "When did Sarah leave?"
- "Where is my phone?" gives its room if your setup knows it, or just that it's at home.
- "Tell Sarah dinner is ready."
- "Turn on the heater" or "What's the fuel level?" for entities you've given to a person.

Anything that changes something takes a preview and a yes. Locks, alarm panels and garage doors also ask before opening or disarming.

## More

- [Reference](docs/reference.md): what is added to the prompt, every tool, privacy and confirmation details, the Last speaker sensor and event, the `get_user_level` action for scripts, repairs, and tips on prompt caching.
- [Changelog](CHANGELOG.md)

## Licence

MIT
