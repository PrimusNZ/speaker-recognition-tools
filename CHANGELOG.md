# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Tests for the prompt text and the config, options and subentry flows, using `pytest-homeassistant-custom-component`.
- `.gitignore`.
- `requirements_test.txt` for the test dependencies.

### Removed
- A committed `__pycache__` file.

## [0.1.0]

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
