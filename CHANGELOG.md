# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
