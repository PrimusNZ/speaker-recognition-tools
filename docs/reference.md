# Reference

The details behind [Speaker Recognition Tools](../README.md). You don't need any of this to get started.

Everything the agent is told, and every rule below, is an instruction to the model. The tools enforce who may see or change what, but the model decides how to word replies and whether to ask for a spoken yes. Nothing here is a security barrier.

- [What is added to the prompt](#what-is-added-to-the-prompt)
- [Names](#names)
- [Tools](#tools)
- [Privacy](#privacy)
- [Locations](#locations)
- [Confirmations and administrator-only entities](#confirmations-and-administrator-only-entities)
- [Recognition confidence](#recognition-confidence)
- [Last speaker sensor and event](#last-speaker-sensor-and-event)
- [Repairs and diagnostics](#repairs-and-diagnostics)
- [Actions for scripts](#actions-for-scripts)
- [Prompt previews](#prompt-previews)
- [Prompt caching](#prompt-caching)
- [Upgrading](#upgrading)

## What is added to the prompt

Up to four sections are added to the conversation agent's system prompt. Speaking Person adds the first three and Speaking Device adds the last. Which of them appear depends on who is speaking.

| Section           | Shown to                                 | What it does                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SPEAKING PERSON` | Everyone                                 | Says who is speaking: their form of address, third-person reference, and the answer to give if they ask who they are. For an unidentified speaker it gives the unknown speaker's form of address. With **Deny unknown speakers** on, an unidentified speaker instead gets a lockdown instruction that overrides the rest of the prompt and makes the agent refuse with one of your refusal lines. |
| `ENTITY MAPPINGS` | Recognised speakers                      | One block per person, in alphabetical order: their name, `Person:` entity, form of address, third-person reference, user level (`User` or `Administrator`), their entities grouped as Calendars, Devices and Other, a `To-do list:` line, and any linked devices. Other people's private entities and aliases are left out. It also names the tools and explains how to use them.                 |
| `PEOPLE`          | Unidentified speakers who are allowed in | A list of people's names, forms of address and third-person references, with no entities, so the agent can recognise household members by any of those. Never shown with **Deny unknown speakers** on.                                                                                                                                                                                            |
| `SPEAKING DEVICE` | Everyone                                 | The id, name and area of the device the request came through. "Here" and "this room" then mean that area. The area is left out when the device has none, and when the device is unknown the agent is told to ask.                                                                                                                                                                                 |

## Names

Only first names go into the prompt and into anything else the model reads, never a full account name. Settings, list entries, the Last speaker sensor, the event and the `get_user_level` action use the person's name from Settings > People instead.

- **Direct address** uses **Address as**, or the first name when it is blank. A third-person reference is never used to address someone directly.
- **Third-person references** use **Third-person reference**, then **Address as**, then the first name.
- People can be identified by first name, **Address as** or third-person reference. They all mean the same person. "Me" means the current speaker.

## Tools

Recognised speakers get sixteen tools. Unidentified speakers, and speakers refused by **Deny unknown speakers**, get none.

| Tool                          | What it does                                                                                                                                                                                                                                                                                                     |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_entity_state`            | Reads the state and attributes of one entity assigned to a person, with its Home Assistant area when it has one. Accepts an entity ID, name or alias. Refused for someone's person entity and trackers when their location is private.                                                                           |
| `control_assigned_entity`     | Calls a Home Assistant service on one assigned entity, such as `switch.turn_on`. It can target only that one entity. Some actions need a preview and a yes first, and administrator-only entities refuse other speakers.                                                                                         |
| `get_calendar_events`         | Reads events on one or more people's calendars between a start and an end. Omitting `people` means the speaker.                                                                                                                                                                                                  |
| `search_calendar_events`      | Finds events by title within a date range and returns IDs for later updates.                                                                                                                                                                                                                                     |
| `check_calendar_availability` | Checks whether a time range overlaps events on one or more calendars.                                                                                                                                                                                                                                            |
| `create_calendar_event`       | Previews an event on one or more people's calendars, then creates it after a yes. The default length is one hour, and a date with no time makes an all-day event.                                                                                                                                                |
| `update_calendar_event`       | Previews a change to one event, then makes it after a yes. Needs a calendar that supports updates.                                                                                                                                                                                                               |
| `delete_calendar_event`       | Previews deleting one event, then deletes it after a yes. Needs a calendar that supports deletion.                                                                                                                                                                                                               |
| `get_person_location`         | Says where people are, using each person's person entity first. Outside every zone it gives the street name and town if their phone reports an address. Each answer says how long they have been there. Leave `people` out to see everyone, which answers "who is home?". Private locations get a privacy reply. |
| `get_person_location_history` | Shows recorded location changes, including when someone arrived or left. Needs Recorder history, and ranges are limited to 31 days. Private locations get a privacy reply.                                                                                                                                       |
| `get_device_location`         | Says where a person's phone or other tracked device is. At home it gives the room if one is known, otherwise just that it is at home. Elsewhere it gives the zone, or the street name and town. See [Locations](#locations).                                                                                     |
| `get_todo_items`              | Reads the open (or completed) items on one or more people's to-do lists.                                                                                                                                                                                                                                         |
| `add_todo_item`               | Previews adding an item, with an optional due date and description, then adds it after a yes.                                                                                                                                                                                                                    |
| `update_todo_item`            | Previews marking an item done or not done, renaming it or changing its due date, then does it after a yes.                                                                                                                                                                                                       |
| `remove_todo_item`            | Previews removing an item, then removes it after a yes.                                                                                                                                                                                                                                                          |
| `send_message_to_person`      | Previews a message to one or more people's phones, then sends it after a yes. It sends to everyone named or to nobody.                                                                                                                                                                                           |

If a person has more than one calendar and the request doesn't say which, the tool returns the choices and the agent asks.

**Calendar changes** always take two calls. The first returns a preview and a confirmation token without changing anything. The agent must ask the speaker and only after a yes call again with the same request and token. A declined or expired preview changes nothing.

**To-do lists.** Each person has at most one, set in their **To-do list** field. The agent calls it "your to-do list" or "Sarah's to-do list". Changes take a preview and a yes. The list must support the change; some can't set due dates. A household list, such as a shared shopping list, is left to Home Assistant's own tools unless it's someone's to-do list.

**Messages.** `send_message_to_person` uses the person's **Message action** and any `notify` entities in their entity list. A private notify entity is only used when its owner messages themselves. If anyone named can't be reached, nothing is sent.

## Privacy

The tools enforce privacy, not just the prompt.

- **Private entities** (including calendars) can be read or changed only by their owner. If someone else asks, the tool says it's private, and a person with one private and one shared calendar looks like they have only the shared one. Other people's private entities are also left out of the prompt.
- **Location is private** hides a person's zone, address and location history from others. Asking where they are, or reading their person entity or trackers directly, gets a privacy reply that tells the agent to say it's private and reveal nothing else. A device at home still answers with its room, or that it is at home. A device elsewhere gets the privacy reply. The person can always see their own.
- **To-do list is private** hides the list from others, and leaves it out of their prompt.
- **Not private** means open to every recognised speaker.

The person entity is always listed for everyone, whatever the setting.

**What this does not protect.** These rules cover this integration's tools and prompt text only. Other tools the agent has, such as Home Assistant's own calendar tool or device controls, can still reach anything exposed to Assist. To keep something away from them, don't expose it to Assist. This integration's tools use whatever you assign, whether or not it's exposed.

Privacy replies are instructions to the model. A model can't forget what it was told earlier in the same chat, so start a new chat after changing a setting.

## Locations

**How long.** The time comes from when the person entity (or the tracker that gave the location) last changed. Home Assistant resets that on restart, so just after one it may say someone has been home only since then. Times are spoken without am or pm, with "this morning", "yesterday evening" or the weekday added when it would otherwise be unclear, and a date for anything older than a week.

**Street addresses.** Outside every zone, the tool looks for an address in this order: an `address`, `geocoded_location` or `formatted_address` attribute on the tracker, then the Companion App's _Geocoded Location_ sensor on the same device. It keeps only the street name and town, using the sensor's `Thoroughfare` and `Locality` attributes when present and otherwise the first line or two of the address. Never the number, postcode or country. Turn the sensor on in the Companion App's settings. It doesn't need to be assigned to the person. If someone marked the sensor private, only its owner gets the address.

Many phones have geocoding off. When someone is outside every zone and no address is found, the tool tells the agent to reply with exactly "Sorry [speaker], An exact address for [person] is unknown." ("for you" when it's about the speaker). Each person is checked on their own.

<a id="device-rooms"></a>**Device rooms.** `get_device_location` finds a device's room from an area sensor on the device whose state is an area name, such as the _Area_ sensor from [Bermuda](https://github.com/agittins/bermuda), or from an `area` attribute on one of its trackers. Any integration that reports areas this way works, and none is built in. A room is only given while the device is at home. If none is known the agent is told only that the device is at home.

For a Companion App phone, turn on the app's _BLE transmitter_ sensor, track that beacon with a BLE tracking integration, and add the beacon's tracker to the person in Settings > People. The tool matches the transmitter's ID to the beacon's device identifiers, so the phone and its beacon count as one device.

Devices come from the person entity's trackers and any trackers assigned to the person. Assigned trackers use their configured name or alias. Others use the device model, or "phone" or "device".

**Location history** is read from Home Assistant Recorder, which must be enabled and keep the period asked for. It shows zone or tracker states and times, not addresses.

## Confirmations and administrator-only entities

Some device actions take two calls, like calendar changes: a preview first, then the action after a spoken yes. This applies to:

- Locks, except locking.
- Alarm panels, except arming.
- Covers whose device class is door, gate or garage, except closing and stopping. Blinds, shades and other covers aren't included.
- Any action on an entity in the person's **Entities that need confirmation** list, or on a linked device with **Actions need confirmation**.
- Any change through the tools when recognition confidence is low (see below).

A confirmation belongs to the speaker who asked for it and to that exact request, and lasts five minutes.

**Administrator-only entities** can be controlled only by speakers whose Home Assistant account is an administrator. Anyone can still read their state.

The tools enforce these rules, so the agent can't skip them. The spoken yes is something the model asks for and reports, not a voice check.

## Recognition confidence

Speaker Recognition sets only the Home Assistant user on each turn, and keeps the match score in its own decision history. When **Minimum recognition confidence for changes** is above 0, this integration reads the current turn's score from that history. If it's below the minimum, every change through the tools needs a preview and a yes, including device actions that normally run straight away, and the agent first asks the speaker to confirm who they are.

That history is internal to Speaker Recognition and may change in any of its releases. When the score can't be read, nothing changes from the behaviour without this setting. The diagnostics download shows whether it can be read. Speaker Recognition's own minimum confidence still decides whether a voice is recognised at all.

## Last speaker sensor and event

Every Speaking Person turn updates the **Last speaker** sensor and fires a `speaker_recognition_tools_speaker` event, so automations can react to who spoke and where. The sensor's state is the speaker's person name, or `unknown_speaker`. Its attributes and the event data include `user_id`, `address_as`, `device_id`, `device`, `area`, `confidence` (from Speaker Recognition, or `null`), `uncertain` and `time`. The event data also has `recognised` and `name`. Typed chats in the Home Assistant app use the signed-in account, so they count as that person speaking.

```yaml
triggers:
  - trigger: event
    event_type: speaker_recognition_tools_speaker
    event_data:
      name: Alex Example
      area: Kitchen
actions:
  - action: light.turn_on
    target:
      area_id: kitchen
```

## Repairs and diagnostics

The integration keeps saved people in step with Home Assistant:

- Renamed entities are updated in every setting that refers to them, including aliases, private and confirmation lists, and linked devices.
- Entities that no longer exist, and missing message actions, raise a Repairs issue for that person or linked device. An entity that is only unavailable isn't reported.
- A person whose user account was deleted or has no name raises a Repairs issue, because that voice is now treated as unknown.
- A speaking person with no person entity, which can happen after an upgrade, raises one. Link a person to their account in Settings > People, then edit them and pick it.
- List entries show the person's name, and note `location private` and `to-do list private` when those are on. Linked devices note `private`, `needs confirmation` and `administrators only`.

Issues clear themselves once the settings are fixed. The diagnostics download (on the integration's menu) describes each person's setup without names, aliases or addresses, so it is safe to attach to an issue. It does include entity IDs.

## Actions for scripts

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

The response has `found`, `is_admin`, `level` (`Administrator` or `User`, or `null` when not found), `configured`, `user_id`, `name` (the person's name, or the account name for anyone without one), `address_as` and, when nothing was found, `reason` (`unknown_person`, `ambiguous_person`, `unknown_user` or `no_user`).

- **Unknown is never an administrator.** An unknown or ambiguous person, an unknown user ID, or no user at all returns `found: false` and `is_admin: false`, so a script that checks `is_admin` fails safe.
- **Accounts that aren't configured people** still get an answer when looked up by `user_id` or by the user who started the script. They return their level and name with `configured: false`. A `person` lookup only matches configured people.
- **`address_as` for anyone who isn't a configured person** is the unknown speaker's form of address (default `Unknown Person`).
- Add `configured` to your check if the script should only trust people you've set up.

## Prompt previews

**Preview prompt** (in the settings) shows what the agent is told for a chosen person or for an unknown speaker. **Preview full prompt** is in the integration page's top action bar, next to **Add person**, and also in the first Add integration menu. It combines the Speaking Person section with a sample Speaking Device section, using the signed-in account when the flow provides it and otherwise the Home Assistant owner. The sample device is any device with an enabled Assist satellite, or unknown if there is none. The preview shows only the APIs you've configured. It doesn't include your conversation agent's own prompt or Home Assistant's wrapper text.

## Prompt caching

This integration adds things that change between requests, such as who is speaking and the device in use. Prompt caching can still reuse an identical prefix before that changing content.

For the best chance of cache reuse, keep your conversation prompt and fixed tool instructions stable. Home Assistant adds selected APIs at the bottom, in the order you added them to the agent, so add APIs with fixed instructions before Speaking Device and Speaking Person. Keep the model and tool definitions stable where possible. Speaking Person only offers tools to recognised speakers, so requests with different tools may not share a cached prefix.

The stable part also has to meet the provider's minimum length for caching, which varies by model. Reuse and lifetime vary too, so this improves the odds of a cache hit but can't guarantee one.

## Upgrading

Saved settings are updated automatically the first time a newer version loads:

- Each speaking person is moved onto the person entity linked to their account. A person entity assigned by hand is removed from their lists, and if it was private, **Location is private** is turned on. Anyone without a matching person gets a Repairs issue.
- Calendars in the entity list move to the **Calendars** field, keeping their private and alias settings. A to-do list in the entity list is used as the person's **To-do list** until you next edit them. If someone had several, only the first is kept.

Home Assistant 2026.10 or later is required, and HACS won't install it on older versions.
