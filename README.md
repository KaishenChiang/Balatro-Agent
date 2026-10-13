# Balatro Agent

English | [简体中文](README.zh-CN.md)

**Let AI take the next run of Balatro.**

A tool-capable AI uses local MCP tools to read player-visible information, choose and execute game actions, and save and reuse what it learns.

For **Windows x64 · Steam Balatro · Codex desktop**. The launcher and play activity window support English and Chinese.

## Download and play

1. **[Download the complete project ZIP](https://github.com/KaishenChiang/balatro-agent/archive/refs/heads/main.zip)** and extract it to a permanent folder. Keep the whole folder. Install the Steam edition of Balatro and sign in to Codex; close the game normally before installation or updates.
2. Open **[Balatro Agent.exe](<Balatro Agent.exe>)** and wait for **Ready**. It finds the project and game, prepares dependencies, backs up and installs the Mods, and configures MCP. No separate Python installation is needed.
3. Choose **Deck** and **Stake / mode**, then click **Start in Codex**. When Codex supports the project link, it opens a project chat with the prompt filled in. Review and **send the prompt in Codex** to begin. The launcher closes after successfully dispatching the opening request.

If the project link does not open, reopen the launcher and use **Copy play prompt**. Paste it into a local Codex chat with the `balatro-agent` tools loaded. Both paths use the same short prompt with the actual project path, your selections and a play-rules file reference, so you do not need to select the project folder first. If tools are missing after setup, reload MCP or reopen Codex.

The launcher follows the Windows display language by default; use **Language / 语言** to switch. You can close the launcher after sending the prompt. Keep the project folder.

## Test other models with CC Switch

You can use **[CC Switch](https://github.com/farion1231/cc-switch)** to configure other model providers in Codex, while keeping this project's local MCP tools. **User-reported gameplay:** DeepSeek V4.1 Flash has been successfully connected through CC Switch and used to play this project. This is a report of that setup working, rather than a compatibility guarantee for every model or evidence of a Gold Stake win.

Prepare the project as above, then select your provider and model in CC Switch's Codex configuration. Follow its [Codex provider and DeepSeek guide](https://github.com/farion1231/cc-switch/blob/main/docs/guides/codex-deepseek-routing-guide-en.md) for the connection format and any required local routing. After applying the configuration, reload or restart your client as needed and check that `balatro-agent` is still loaded. Send the same play prompt and follow [the play rules](prompts/bootstrap.en.md); keep only one model operating a game instance at a time.

The selected model and connection must support tool calls and continued tool feedback. Verify launch, connection and actual actions before evaluating gameplay; a provider switch alone does not establish compatibility. Accounts, API keys and model charges are managed by your client/provider, not by this project. [Client configuration and checks](docs/balatro-ai/model-client.md)

## Live play activity

An MCP game launch opens an independent activity window. Its **HH:mm:ss** timeline shows stage changes, short decisions, plan updates, action results, and experience saves. It displays the model's submitted rationale and plans.

Drag the window edges to resize its width and height; text wraps automatically. Close it at any time without interrupting play; double-click **[Balatro Status.exe](<Balatro Status.exe>)** to reopen it. The command `Balatro Agent.exe --monitor` also works. [How it works and measured overhead](docs/balatro-ai/activity.md)

Each run automatically keeps a JSONL activity file and a Chinese TXT editing timeline under `runs/live/activity/by-run/`. Normal results and post-run experience saves stay with that run. Open **Log folder**, then `by-run`. The timeline includes actual timestamps and elapsed recording time: align one shared event with your video before editing. Mid-run attachment and reconnect gaps are labeled; these are not video timecodes.

## Decks and stakes

The default is **Red Deck / White Stake**. Choose from **15 original decks**; the selected deck must be visibly unlocked. After you send the play prompt, the AI first opens or shows the game, then checks the connection.

| Stake / mode | Behavior |
| --- | --- |
| White, Red, Green, Black, Blue, Purple, Orange, Gold | One run at the selected stake |
| Highest stake | One run at the highest unlocked stake for that deck |
| Climb mode | Start at that deck's highest unlocked stake; retry normal losses, advance one stake after a verified win, and continue until beating Gold or you ask to stop |

Highest stake ignores locked candidates, including unnamed ones, and compares only unlocked, enabled choices. Climb mode reports and reviews each run before continuing. Connection faults or uncertain results require recovery and are not retried as normal losses.

## Results and experience

Each completed run returns a brief report: **actual deck / stake · win or loss · ante / round · elapsed time · experience update status**.

After a single run or a completed climb, **the game stays on the results screen with its window open**. A climb continues after each run's report.

The AI reads the [general guide](experience/README.md) before playing and other topics as needed. Both source baselines and local experience keep one `current.md` per topic; local updates amend and atomically replace that same file. Chinese guides contain rules, conditions, counterexamples and confidence. Provenance and save receipts are separate audit metadata, omitted from default gameplay reads. Local experience takes priority and stays in `runs/local-experience/` without automatic upload. Back up and migrate that entire folder, including `.metadata/`, when moving or re-downloading the project.

## More information

[Setup and recovery](docs/balatro-ai/maintenance.en.md) · [English support](docs/balatro-ai/english-support.md) · [Play rules](prompts/bootstrap.en.md) · [Verification evidence](evidence/README.md) · [Changelog](CHANGELOG.md)

If this project helps you, a **Star** is welcome. Report problems in [Issues](https://github.com/KaishenChiang/balatro-agent/issues).

## License

Self-authored code, documentation, and experience use the [MIT License](LICENSE). Third-party licenses are listed in [NOTICE](third_party/NOTICE.md).
