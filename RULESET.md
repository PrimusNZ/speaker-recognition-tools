# Person identity and addressing rules

These rules describe how the integration tells a conversation agent to identify and address a configured person. Prompt text is an instruction to the model, not enforcement.

## Person fields

- `NAME` is the person's first name from their Home Assistant account. A configured person always has a name; without one, that speaker is treated as unknown.
- `ADDRESS_AS` is optional and controls how the agent addresses the person directly. The UI label is **Address as**.
- `THIRDPERSON` is optional and controls how the agent refers to the person when speaking about them.

## Direct address

Use `ADDRESS_AS` when directly addressing the person. If it is not configured, use `NAME`. Never use `THIRDPERSON` as a direct form of address, even when it is configured.

This applies to `[direct address]` substitute tags in the conversation agent's prompt.

## Identity answer

When the person asks who they are, use exactly the sentence for their configured fields:

| Third-person reference | Address as | Answer |
| --- | --- | --- |
| Set | Set | `You are THIRDPERSON, your form of address is ADDRESS_AS, and your name is NAME.` |
| Not set | Set | `Your form of address is ADDRESS_AS, and your name is NAME.` |
| Set | Not set | `You are THIRDPERSON, and your name is NAME.` |
| Not set | Not set | `Your name is NAME.` |

## Referring to people

When speaking about someone in the third person, including in tool results, use the first available value in this order:

1. `THIRDPERSON`
2. `ADDRESS_AS`
3. `NAME`

This applies when tool results are about the current speaker as well as other people. Direct salutations to the speaker continue to follow the direct-address rule above.

**Direct-reply exception:** A tool may provide an exact reply intended to be spoken directly to the current speaker. In that reply, it may refer to the speaker as “you” or “your.” The salutation must still use their configured address form, falling back to their name; never use their third-person reference to address them. References to anyone else in the reply must follow the third-person fallback order.

## Understanding references

People may identify a household member by their first name, configured address form, or third-person reference. Treat all configured forms as referring to the same person. The integration's tools also resolve those forms when selecting a person.
