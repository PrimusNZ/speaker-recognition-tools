# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.10.3] - 2026-11-08

### Added

- Household devices: a new **Household devices** setting (gear icon) for shared entities that aren't assigned to a person, such as an air conditioner. Two new tools, `get_household_device_state` and `control_household_device`, read and control them. Anyone who isn't denied can use them, including unknown speakers. Unknown speakers can never use locks, alarm panels, or door, gate or garage covers, which are refused in the tools and left out of their prompt. Calendars cannot be household devices, and a device that another person has marked private is not shared. A new `HOUSEHOLD DEVICES` prompt section lists them with their area and floor.
- Household device aliases: a **Household device aliases** setting (one `entity_id: alias, another alias` line per device, like people's entity aliases) gives devices alternate names, such as "aircon". The first alias is the preferred name. Aliases set on the entity in Home Assistant count too. Several devices can share an alias and the room rules still choose between them.
- The same words work in every room. When several household devices match a name, the one in the area of the device the speaker is using is chosen, then one on the same floor. A room or floor the speaker names wins, and if it is still unclear the agent is given the choices and asks.
- Better climate control, for household devices and for assigned entities: the tool description now names `climate.set_hvac_mode`, `set_temperature`, `set_fan_mode` and `set_swing_mode`. Modes are matched without regard to case or spaces, a mode the unit doesn't support is refused with the modes it does, and a temperature outside the unit's range is refused with the range. After a climate action the result shows the resulting mode, target temperature, fan and swing settings.

### Fixed

- Controlling a unit that is slow to report its new state, such as a cloud-connected air conditioner, no longer looks like a failure. After a household device or assigned entity action the tool waits up to 5 seconds for the unit to show the result (returning as soon as it does, or at once if it already shows it). If it still hasn't, the result says `state_confirmed: false` with a note telling the agent to say the command was sent and is not confirmed yet, instead of reporting that it failed.

## [0.10.2.2] - 2026-11-02

### Changed

- Add a Security disclaimer to the top of the README, and replace "MIT" in its Licence section with the full licence text.
- Add a Prompt caching section and a Good to know section to the README, covering rooms for "Where is my phone?", location history limits, which actions ask for a yes, the `[direct address]` placeholder, upgrading, and the sensor, event and action for automations.

## [0.10.2.1] - 2026-11-02

### Changed

- Rewrite the README to be shorter and plainer, and move the technical details into `docs/reference.md`. The text was checked against how the integration works now, and corrections include: person entities and their linked phones are shared automatically and are not entities to assign, Speaking Device also gives the area, the entity mappings section always appears for recognised speakers, and it is installed through HACS.
- Remove `EXAMPLE_PROMPT.txt`. The README now has the one paragraph to paste into your agent's prompt, in a code block.
- Use "The breadwinner" as the third-person reference example in the form help text and the README, and a to-do list example that suits a personal list.
- When a device is at home and no room is known, `get_device_location` now tells the agent to say the device is at home, naming the person and the device, and nothing else about where in the house it is.

## [0.10.2] - 2026-11-02

### Changed

- Rework **Location is private**. The person entity is now listed for everyone. Asking where a private person is, or for their location history, gets a privacy reply, and so does reading their person entity or trackers directly. Asking where their phone or other device is still works: a device at home gives its room or "home", and a device away from home gets a privacy reply. The setting description now says so.
- Show private settings in the speaking person list: a person with **Location is private** or **To-do list is private** turned on says `location private` or `to-do list private`, and a linked device says `private`, `needs confirmation` or `administrators only` for the flags that are on. Existing entries update on the next restart.

## [0.10.1] - 2026-11-02

### Added

- Add `get_device_location`, which answers "where is my phone?" and "where is Sarah's phone?". It uses the person's assigned device trackers and the trackers of their assigned person entity, and gives the room (Home Assistant area) when the device is at home and a room is known from any integration that reports areas, such as Bermuda. A Companion App phone and the BLE beacon tracker for its transmitter, both on the person entity, are reported as one device. Otherwise it gives the zone, or the street name and town outside every zone.

### Changed

- Build each speaking person on a **Person** (`person` entity) instead of a user account. The account comes from the person, and the person entity belongs to them automatically: it is used for their location and shown as a `Person:` line at the top of their prompt block. A new **Location is private** switch keeps their location to themselves. The entity list no longer accepts person entities. Existing people move onto the person linked to their account the first time this version loads, dropping any person entity assigned by hand and keeping it private if it was. Anyone with no matching person gets a Repairs issue and can pick one by editing them.
- Show the person's name as a heading at the top of their edit form.
- Use the person's name, not the first name, for the **Last speaker** sensor's state, the `name` in the `speaker_recognition_tools_speaker` event and the `name` returned by `get_user_level`. Automations that compare these with a first name need updating. First names are now only used in the prompt and other text the model sees.
- List each speaking person, and each linked device's person, under the person's name instead of their account's first name. This covers the linked-device person picker too. Existing entries are renamed automatically, and follow later changes to the person's name.
- Add a **Calendars** field for each person's calendars. To make a calendar private, add it to Private entities, as before; entity aliases work for calendars too. The entity list no longer accepts calendars, and existing calendars move to the new field when this version first loads, keeping their private and alias settings.
- Reorder the person form: Location is private and To-do list is private come first, then Address as, Third-person reference, Entities, Entity aliases, To-do list, Calendars, Private entities, Entities that need confirmation, Administrator-only entities and Message action.
- Give each person one to-do list, set in a new **To-do list** field with a **To-do list is private** switch, instead of to-do lists in the entity list. The to-do tools no longer ask which list to use, and the agent calls it "your to-do list" or "[name]'s to-do list". People set up earlier keep their first assigned to-do list and its private setting; any other to-do lists they had are no longer used. The entity list no longer accepts to-do lists.

## [0.10.0] - 2026-11-02

### Added

- Ask for a spoken yes before unlocking a lock, disarming an alarm panel, or opening a door, gate or garage door cover through `control_assigned_entity`. Locking, arming, closing and stopping still run straight away.
- Add per-person **Entities that need confirmation** and a linked-device **Actions need confirmation** option, which make every action on those entities wait for a spoken yes.
- Add per-person **Administrator-only entities** and a linked-device **Actions are for administrators only** option. Only administrator speakers can control them; anyone can still read their state.
- Add per-person to-do list tools: `get_todo_items`, `add_todo_item`, `update_todo_item` and `remove_todo_item`. Changes are previewed and need a yes. Household lists, such as a shared shopping list, are left out unless assigned to a person.
- Add `send_message_to_person`, which previews and then sends a message to a person's phone through their new **Message action** setting or their assigned notify entities.
- Add a **Last speaker** sensor and a `speaker_recognition_tools_speaker` event, updated on every Speaking Person turn with the speaker, device, area and recognition confidence.
- Add **Minimum recognition confidence for changes**. When Speaker Recognition scores a turn below it, every change through the tools needs a yes and the agent first confirms who is speaking. The score is read from Speaker Recognition's internal decision history; when it cannot be read, nothing changes.
- Raise Repairs issues for people or linked devices that refer to entities or message actions that no longer exist, and for people whose user account was deleted. Renamed entities are now updated automatically in every setting.
- Add a diagnostics download that describes each person's setup without names, aliases or addresses.
- List to-do lists as their own group in entity mappings.

### Changed

- `speaker_recognition_tools.get_user_level` now returns the Speaking Person's configured unknown speaker address form as `address_as` for anyone who is not a configured person, instead of `null`.
- Require Home Assistant 2026.10 or later. HACS now blocks installs on older versions, and the compatibility code for older versions is removed. Older versions previously failed to load the integration.

### Fixed

- Look up Assist devices for the full-prompt preview without the deprecated device registry mapping access, which stops working in Home Assistant 2027.9.

### Developer

- Load configured people from one shared module for the prompt, tools, previews and actions, instead of separate copies.
- Split the tools into entity, calendar, location, to-do and message modules with shared helpers, and split the tool tests to match under `tests/tools/`.

## [0.7.0] - 2026-11-02

### Added

- Include each configured person's Home Assistant user level in the prompt mappings.
- Add the `speaker_recognition_tools.get_user_level` action, which returns a person's user level (`User` or `Administrator`) as a response so scripts and automations can allow or block actions by level. Unknown or ambiguous people are never reported as administrators.

### Fixed

- Add the missing space between the "current speaker" sentence and the alias guidance in the entity mappings intro.

## [0.6.0.5] - 2026-10-27

### Fixed

- Render prompt previews as Markdown directly, removing the nonfunctional alert wrapper and separating the prompt from disclaimers with horizontal rules.

### Developer

- Document test naming, changelog ordering, and SSHFS-based Home Assistant development and restart procedures in `AGENTS.md`.

## [0.6.0.4] - 2026-10-26

### Changed

- Format linked-device aliases, status entities, and action entities as nested prompt bullets.
- Render Markdown formatting inside the shaded full-prompt preview alert.

### Developer

- Add Ruff and Prettier configuration and formatting commands.

## [0.6.0.3] - 2026-10-26

### Changed

- List people alphabetically in entity mappings instead of putting the current speaker first.
- Omit privacy markers and privacy instructions from prompt text while continuing to enforce privacy in tools.

## [0.6.0.2] - 2026-10-26

### Fixed

- Complete linked-device support by routing aliases to the configured status and action entities.
- Place linked-device reconfigure translations under the supported flow step section.

### Documentation

- Use synthetic location examples in the README and tests.

## [0.6.0.1] - 2026-10-26

### Added

- Add linked devices that map one spoken name to separate status and action entities.

## [0.6.0] - 2026-10-26

### Added

- Add tools to read assigned entity states and call Home Assistant services on assigned entities, with per-person privacy checks.

## [0.5.0.2] - 2026-10-26

### Fixed

- Use a reported street and town as the location when someone is outside every zone, instead of describing them as away.

## [0.5.0.1] - 2026-10-26

### Fixed

- Use a colon between entity IDs and display names in prompt mappings, matching the aliases field format.

## [0.4.0] - 2026-10-26

### Added

- Allow aliases to be assigned to a person's entities, shown in prompt mappings, and used to select calendars in tools.

## [0.3.0] - 2026-10-26

### Changed

- Rename the person and unknown-speaker configuration fields to Address as, while retaining support for existing saved settings.

## [0.2.0] - 2026-10-26

### Changed

- Replace the `[title]` prompt placeholder with `[direct address]`, which also covers the first-name fallback.
- Clarify README person-addressing fallbacks, accepted tool aliases and location reply wording.
- Document first-name, title and third-person reference aliases in every person tool description.
- State the direct-address and third-person fallback order consistently in every generated people section.
- Document the direct-reply exception for exact tool replies to the current speaker.
- Use each person's third-person reference in the identity answer when configured, and clarify that people can refer to household members by name, title or reference.
- Fall back from a missing third-person reference to the title, then to the person's first name.
- Keep direct address on the title, falling back to the first name, even when a third-person reference is configured.
- Use the configured identity fields in the exact answer given when a speaker asks who they are.
- Align the example prompt with direct-address, person-reference and calendar-confirmation behavior.

## [0.1.2] - 2026-10-26

### Added

- Added an optional per-person third-person reference, separate from the title used for direct address.

## [0.1.1.3] - 2026-10-26

### Fixed

- Keep every section of a multiline prompt inside the shaded preview box.

## [0.1.1.2] - 2026-10-26

### Fixed

- Full prompt previews now sample only devices with an enabled Assist satellite entity. Prompt previews use a shaded, wrapping box instead of a horizontally scrolling code block.

## [0.1.1.1] - 2026-10-26

### Fixed

- Full prompt previews now put the device example disclaimer first, followed by a `Prompt Preview:` label and a code block containing only the prompt. The person prompt preview also labels and displays its prompt in a code block.

## [0.1.1] - 2026-10-26

### Changed

- The full prompt preview now identifies its Speaking Device section as an example that may use a randomly selected registered device. The disclaimer appears only when Speaking Device is configured.

## [0.1.0] - 2026-10-26

### Added

- Added an integration-level full prompt preview that includes only configured API sections and works without any person subentries.

### Changed

- Replaced the default refusal lines with the new set of 20 responses.

## [0.0.9] - 2026-10-26

### Documentation

- Added guidance on arranging stable and per-request prompt content to improve cache reuse.

### Added

- Added calendar search, availability, update and delete tools, recorded location history, and an unknown-speaker prompt preview.
- Calendar event creation, updates and deletions now require a preview and explicit confirmation before changing a calendar.

## [0.0.8] - 2026-10-26

### Added

- Speaking Person settings now include a prompt preview for each configured person.
- Person configuration warns about stale entity IDs and entities assigned to multiple people, and requires acknowledgement before saving those assignments.

## [0.0.7] - 2026-10-26

### Added

- The SPEAKING DEVICE section now includes the device's area, so "here" and "this room" resolve. For example, it says the device is in the Lounge area and that "here" means the Lounge. Left out when the device has no area.
- `get_person_location` now says how long someone has been home or away, ready to say aloud, such as "home since three o'clock". Times are spoken without am or pm.

## [0.0.6.1] - 2026-10-26

### Fixed

- Entity groups in the ENTITY MAPPINGS section are now separated by a blank line. Without it, a markdown renderer folded a group heading such as "Devices:" into the end of the previous list item.

## [0.0.6] - 2026-10-25

### Changed

- When someone is away and no address is known, `get_person_location` now tells the agent to reply with exactly "Sorry [speaker's title], An exact address for [person's title] is unknown." ("for you" when asking about themselves) and nothing else. When an address is known, only the street name and town are given, never the street number, postcode or country. The wording lives in the tool, so the example prompt no longer covers it.

## [0.0.5] - 2026-10-25

### Added

- `get_person_location` now includes a street address when someone is away, outside every zone, and their device tracker or the Companion App's geocoded location sensor reports one. A sensor another person has marked private is never read. When a phone has no geocoding, the result says "An exact address for [title] is unknown" and tells the agent not to guess a place.

## [0.0.4] - 2026-10-25

### Added

- **Tools for recognised speakers**: `get_calendar_events`, `create_calendar_event` and `get_person_location`. They work on the entities assigned to each person, accept several people in one request (for example "Sarah's and my calendars"), and return a choice to ask the speaker when a person has more than one calendar. Creating an event is all-or-nothing. Unidentified and refused speakers get no tools.
- **Private entities**: each person can mark some of their assigned entities as private. Only the owner can use them through the tools, other people's private entities are left out of the prompt, and the owner's own are marked `(private)`. The settings list shows the count, for example "James: Dad (3 entities, 1 private)".
- `EXAMPLE_PROMPT.txt` now covers the tools and private entities.
- A prominent README warning that assigned entities bypass Assist's exposed-entities setting.

## [0.0.3] - 2026-10-25

### Added

- `EXAMPLE_PROMPT.txt`, a complete example conversation agent prompt that works with the injected sections.
- README setup step with a paragraph to add to the conversation agent's prompt, and a table summarising the sections added to the prompt.
- Tests for both LLM APIs and for entry setup, unload, reload and removal.

### Changed

- The default title for unknown speakers is now "Unknown Person" instead of "Infiltrator". Existing entries keep the title they already have.

## [0.0.2] - 2026-10-25

### Added

- The list of people in the settings shows how many entities each person has, for example "James: Dad (3 entities)".
- Only first names are ever used in the prompt, never the full account name.
- A person's title is now optional. When it is left blank, the first name on their Home Assistant account is used.
- Each person can have entities assigned (calendars, the Companion App phone's device tracker or sensors, and so on). The prompt lists them as an ENTITY MAPPINGS section with one block per person, grouped into Calendars, Devices and Other, so "What's on my calendar?" uses the speaker's own entities, "What is Sarah doing on Friday?" uses Sarah's, and a request naming several people uses each person's. Existing people keep working with no entities.
- Speaking Person now lists the other configured people with their titles and tells the agent to refer to them by title (Dad) rather than name (James). Unknown speakers get the list of people and titles but no entities, and known speakers see themselves first, then the others alphabetically.
- Tests for the prompt text and the config, options and subentry flows, using `pytest-homeassistant-custom-component`.
- `.gitignore`.
- `requirements_test.txt` for the test dependencies.

### Removed

- A committed `__pycache__` file.

## [0.0.1] - 2026-10-18

### Added

- **Speaking Person** LLM API. It tells the agent the speaker's title, using the Home Assistant user that Speaker Recognition sets on each request.
  - People are added as subentries under the integration, each linking a Home Assistant user to a title.
  - Unknown speakers get a configurable title (default "Infiltrator").
  - **Deny unknown speakers** option (off by default), with configurable refusal lines. The deny prompt overrides all other instructions in the agent's prompt.
  - Speakers are referred to only by title. Asking "who am I" is answered with name and title.
  - `[title]` in the agent's own prompt is replaced with the current speaker's title.
- **Speaking Device** LLM API. It tells the agent the id and name of the device being spoken through, or that the device is not known.
- `SPEAKING PERSON` and `SPEAKING DEVICE` headings on the injected text, worded to match the existing CABAL prompt sections.
- Plain menu labels and an icon for the integration.
- HACS support.
