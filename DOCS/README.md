# Design notes

This is where we work out an API before implementing it. Start with the code
someone would write, explain what it means, and decide whether it belongs in
fetch.py at all.

These are working notes. Proposed methods and options are **not available**
unless a note explicitly identifies them as current behavior. The main
[README](../README.md) describes the current prototype.

## Topics

| Topic | Question |
| --- | --- |
| [Pydantic](pydantic.md) | How should typed validation compose with a response? |
| [Logging](logging.md) | How can callers see what happened without configuring another system? |
| [Single file](single-file.md) | What does copying the library into a project promise? |

## Adding a topic

Use a short filename such as `timeouts.md` or `streaming.md`. Include:

1. **Status and purpose.** Current behavior, proposal, or an open question.
2. **An example.** Show the smallest useful call; mark proposed syntax clearly.
3. **Behavior.** Return values, errors, defaults, and ownership of resources.
4. **Cost.** Dependencies, complexity, and impact on copying the file.
5. **A recommendation and open questions.** Have a point of view without
   presenting a sketch as a settled contract.

Link to other topics when they share a decision. Keep implementation work out
of a topic until its examples and tradeoffs are clear.
