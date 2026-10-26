# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

A Home Assistant custom integration (`speaker_recognition_tools`, distributed through HACS). Repository: `PrimusNZ/speaker-recognition-tools`. It adds two LLM APIs for conversation agents: Speaking Person and Speaking Device. They tell the agent who is speaking and which device they are using. It depends on the separate Speaker Recognition project, which sets the Home Assistant user for each request. This integration only reads that result.

See `README.md` for behaviour and `EXAMPLE_PROMPT.txt` for the sample conversation prompt.

## Layout

- `custom_components/speaker_recognition_tools/`
  - `__init__.py`: entry setup.
  - `config_flow.py`: config and options flows, person subentries, prompt preview, entity checks.
  - `const.py`: constants.
  - `llm_api.py`: the two LLM API classes.
  - `prompt.py`: builds the prompt sections (`SPEAKING PERSON`, `ENTITY MAPPINGS`, `PEOPLE`, `SPEAKING DEVICE`).
  - `tools.py`: ten tools for assigned entity state and control, calendars, and locations, with privacy enforcement.
  - `translations/en.json`: UI strings.
  - `manifest.json`: integration metadata, including `version`.
- `tests/`: one test module per source module, using `pytest-homeassistant-custom-component`.

Speaking Person offers ten tools to recognised speakers: `get_entity_state`, `control_assigned_entity`, `get_calendar_events`, `search_calendar_events`, `check_calendar_availability`, `create_calendar_event`, `update_calendar_event`, `delete_calendar_event`, `get_person_location`, and `get_person_location_history`. Unknown or refused speakers receive no tools.

The full-prompt preview combines the Speaking Person section with a sample registered device's Speaking Device section. It uses the signed-in account when the options flow provides its ID, otherwise the Home Assistant owner account. The sample device is illustrative; Home Assistant controls the order of selected APIs. The preview excludes the conversation agent's own prompt and Home Assistant's API wrapper text.

## Commands

Run the full suite with `.venv/bin/pytest` after code or behaviour changes. Add or update tests for new behaviour. Run pytest outside the sandbox as requested by the project owner; do not ask for permission again.

After changes, run `.venv/bin/ruff check .` and `npm run format:check`. If Prettier reports files that need formatting, run `npm run format`, review the diff, then rerun Ruff, Prettier, and pytest as applicable. Prettier is installed through npm; use `npm ci` if `node_modules` is missing.

`asyncio_mode = "auto"` is set in `pyproject.toml`. Python and test dependencies live in `.venv` (see `requirements_test.txt` and `requirements_dev.txt`).

## Home Assistant development instance

- Develop and test integration changes against the installed Home Assistant copy using SSHFS. Keep the SSH destination, remote integration directory, local mountpoint, and remote backup directory in the developer's private `~/.config/speaker-recognition-tools/ha-dev.env` file; do not put machine-specific hostnames, IP addresses, usernames, or filesystem paths in tracked project files.
- Source that private configuration before mounting or using SSH. Mount the configured integration directory, then edit files through the mount. Changes there write directly to the installed files.
- Changes written through the mount update the installed files directly. Keep the repository source in sync with changes made through the mount, and keep tests, changelog, and documentation in this repository.
- Before replacing an installed file outside the mount, preserve its current copy in the configured remote backup directory. The mount is the normal path for direct development edits.
- After every change to the installed integration files, run the Home Assistant configuration check, perform a full Home Assistant restart, allow about five minutes for startup, and then verify the integration loaded. Config-entry reloads do not reliably apply these changes; do not use them as a substitute for restarting.
- Do not publish a development change to GitHub until the user confirms testing is complete and explicitly requests the relevant commit, push, version bump, or release. Each action still requires an explicit request.

## Conventions

- Match the surrounding code's style, naming and comment density.
- Treat this file as standing agent guidance. Update it without asking only when the user gives a new rule or instruction; do not update it for ordinary task details. Whenever you update this file, end the response with a concise all-caps notice that it was updated.
- Add or update tests with every behaviour change.
- When adding or editing tests, review each affected test name against what it actually verifies. Use concise, behavior-focused names and current project terminology; rename names that are vague, awkward, or stale.
- Do not use real-world data or examples provided by the user in tests, documentation, or other project examples unless explicitly asked. Generate sensible synthetic data instead.
- Use only first names in anything shown to the model, never full account names.
- Privacy is enforced in the tools, not just the prompt. A private entity can be read or written only by its owner, and other people's private entities are left out of prompts. Keep that true for any new tool.
- Calendar create, update and delete take two calls: a preview with a confirmation token, then the change. Keep that flow for any new write tool.
- Fixed reply wording belongs in tool results (for example "reply with exactly ..."), not in `EXAMPLE_PROMPT.txt`. Edit `EXAMPLE_PROMPT.txt` only when absolutely needed, such as removing a line that now conflicts with a tool. Do not modify the user's live conversation prompt unless explicitly asked.
- A tool result or prompt text is an instruction to the model, not enforcement. Say so in docs.
- Update `README.md` when behaviour, tools or prompt sections change. Keep the warnings about entities bypassing Assist's exposed-entities setting accurate.
- Keep prompt-caching guidance provider-neutral unless asked otherwise. Home Assistant appends selected APIs at the bottom of the conversation prompt in the order they were added; this integration cannot choose that order.
- Location history requires Home Assistant Recorder history and is limited to 31 days.

## Changelog and releases

- Record changes in `CHANGELOG.md` under `## [Unreleased]` (Keep a Changelog format). Remove the `## [Unreleased]` heading before a commit and never include that heading in the commit; add it back when recording a subsequent change.
- Keep changelog sections in descending version order, with `## [Unreleased]` first and immediately above the latest release.
- Never rewrite the text of an already-released entry.
- Use `vX.X.X` versions for releases. When the final component reaches 9, roll it to 0 and increment the minor component (for example, `v0.0.9` → `v0.1.0`, `v0.4.9` → `v0.5.0`, and `v0.9.9` → `v0.10.0`). Bug fixes use a fourth component (for example, `v0.1.0.1`). Major versions change only when the project owner explicitly requests one. Follow the established release format.
- Commit, push, bump the version, or create a release only after the user confirms testing is complete and explicitly asks for that action in the current request. Otherwise leave the work uncommitted and do not mention that solely for being uncommitted.
- Use `gh` for GitHub actions. Push with `git -c credential.helper= -c credential.helper='!gh auth git-credential' push`.
- Commit messages are short imperative summaries with the version in parentheses, for example `Add prompt preview and entity configuration checks (0.0.8)`. Do not add another author or co-author, a `Co-Authored-By` trailer, or `Generated with Claude Code` or similar attribution to commits, PRs, or release notes.
- Match the existing release format: title/tag `vX.X.X`, notes copied from the matching changelog section, followed by a `Full changelog` compare link.
- After a new version is released, update the integration in Home Assistant through HACS. If HACS reports success, restart Home Assistant and verify the integration loaded.
- A version bump means updating `manifest.json` and moving the `Unreleased` changelog entries under the new version heading.
