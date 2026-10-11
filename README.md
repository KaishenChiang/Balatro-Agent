# Balatro Agent

English | [简体中文](README.zh-CN.md)

**Let AI take the next run of Balatro.**

A tool-capable AI uses local MCP tools to read player-visible information, choose and execute game actions, and save and reuse what it learns.

For **Windows x64 · Steam Balatro · Codex desktop**. The launcher and play activity window support English and Chinese.

## Download and play

1. **[Download the complete project ZIP](https://github.com/KaishenChiang/balatro-agent/archive/refs/heads/main.zip)** and extract it to a permanent folder. Keep the whole folder. Install the Steam edition of Balatro and sign in to Codex; close the game normally before installation or updates.
2. Open **[Balatro Agent.exe](<Balatro Agent.exe>)** and wait for **Ready**. It finds the project and game, prepares dependencies, backs up and installs the Mods, and configures MCP. No separate Python installation is needed.
3. Choose **Deck** and **Stake / mode**, then click **Start in Codex**. When Codex supports the project link, it opens a project chat with the prompt filled in. Review and **send the prompt in Codex** to begin. The launcher closes after successfully dispatching the opening request.

If the project link does not open, reopen the launcher and use **Copy play prompt**. Paste it into a local Codex chat with the `balatro-agent` tools loaded. The prompt includes the actual project path and your selections, so you do not need to select the project folder first. If tools are missing after setup, reload MCP or reopen Codex.

The launcher follows the Windows display language by default; use **Language / 语言** to switch. You can close the launcher after sending the prompt. Keep the project folder.

## Live play activity

An MCP game launch opens an independent activity window. Its **HH:mm:ss** timeline shows stage changes, short decisions, plan updates, action results, and experience saves. It displays the model's submitted rationale and plans.

Close the window at any time without interrupting play; reopen it with `Balatro Agent.exe --monitor`. [How it works and measured overhead](docs/balatro-ai/activity.md)

## Decks and stakes

The default is **Red Deck / White Stake**. Choose from **15 original decks**; unlocks are checked in the game. Locked or unconfirmed choices are reported and stopped.

| Stake / mode | Behavior |
| --- | --- |
| White, Red, Green, Black, Blue, Purple, Orange, Gold | One run at the selected stake |
| Highest stake | One run at the highest unlocked stake for that deck |
| Climb mode | Start at that deck's highest unlocked stake; retry normal losses, advance one stake after a verified win, and continue until beating Gold or you ask to stop |

Climb mode reports and reviews each run before continuing. Connection faults or uncertain results require recovery and are not retried as normal losses.

## Results and experience

Each completed run returns a brief report: **actual deck / stake · win or loss · ante / round · elapsed time · experience update status**.

After a single run or a completed climb, **the game stays on the results screen with its window open**. A climb continues after each run's report.

The AI reads the [general guide](experience/README.md) before playing and other topics as needed. New experience stays in `runs/local-experience/` and is not uploaded automatically. Back up and migrate that folder separately when moving or re-downloading the project.

## More information

[Setup and recovery](docs/balatro-ai/maintenance.en.md) · [English support](docs/balatro-ai/english-support.md) · [Play rules](prompts/bootstrap.en.md) · [Development and verification](PROJECT.md) · [Changelog](CHANGELOG.md)

If this project helps you, a **Star** is welcome. Report problems in [Issues](https://github.com/KaishenChiang/balatro-agent/issues).

## License

Self-authored code, documentation, and experience use the [MIT License](LICENSE). Third-party licenses are listed in [NOTICE](third_party/NOTICE.md).
