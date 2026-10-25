# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
