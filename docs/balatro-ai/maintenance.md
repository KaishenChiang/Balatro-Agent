# 安装、维护与恢复

[English](maintenance.en.md) | 简体中文

项目只有一个STDIO服务；游戏观察和操作通过MCP，维护脚本不替模型作策略决策。工具契约见[技术参考](reference.md)，验证范围见[PROJECT](../../PROJECT.md)。

## 首次安装

Windows x64用户双击根目录[Balatro Agent.exe](<../../Balatro Agent.exe>)。窗口自动检查Steam安装元数据，无需预装Python或uv；使用vendor内的固定发行归档，在项目内准备Python3.13.11和隔离依赖，构建Mod、冻结安装方案、核验备份并追加Codex配置。成功后提供“在 Codex 中开始”和“复制游玩提示”。项目目录须长期保留。

用户可选择15种原版牌组和8个固定注级、最高已解锁注级或爬塔模式，默认红色牌组／白注单局。解锁情况由模型在游戏内通过当前MCP公开候选核验；目录中的选项不证明已解锁。最高注级尝试一局，爬塔从该牌组最高已解锁注级开始，正常失败重试当前等级、胜利后核验并升一级直至金注通关，单局／最高模式不自动重试。

“在Codex中开始”通过官方项目链接传入实际目录、当前选择与目标提示，只预填并等待用户发送；复制入口与项目链接共用短提示，附带路径、选择与bootstrap文件入口，可直接在已加载MCP的本地Codex聊天发送。未注册协议或打开失败时使用复制入口，底部仍保留项目路径供排障。提示中的路径不改变已有聊天的工作目录或文件权限，准备收据不证明客户端已经加载MCP。[官方项目链接](https://learn.chatgpt.com/docs/reference/commands#chats)

项目链接打开请求成功发出后，启动器自动关闭。此时仍须用户在Codex发送提示，不表示游戏已经开始；MCP由客户端独立管理。复制提示、链接失败或安装页面降级流程保留窗口，准备未结束时仍拒绝关窗。启动器可以关闭，完整项目目录需保留。

EXE是唯一桌面入口，C#源码和构建收据在windows/；重复的CMD启动和安装包装已移除。vendor包含公开的上游原始归档，先核对整包和各成员SHA-256，再通过本地Python镜像与wheel目录离线准备，不需要复制现成venv。运行依赖和构建依赖的版本、URL、哈希及许可见[运行锁](../../config/runtime.lock.json)；Mod与uv见[组件锁](../../config/dependencies.lock.json)。完整包无需联网下载组件。

窗口底部“详情”显示本次日志。维护副本缺少内置归档时才使用下载或旧缓存；下载显示字节量和速度。uv下载每次连接与读操作上限20秒、至多重试一次；低于1 KB/s持续30秒或单次总计10分钟会停止。已有部分文件复制后续传，原文件保留，必须核对Range和最终完整SHA256；服务器不支持Range时保存前缀并重新下载。默认读取系统代理，显式HTTPS_PROXY优先，不修改系统网络设置。Python和Mod下载仍分别遵循uv及公开源校验；不把进度或网络成功当成安装完成。

游戏未安装时在下载依赖前提示；需要安装或更新时游戏须正常关闭。已有完整的项目安装按账本与构建哈希核验，直接复用；有源码更新时只更新已记录的项目Mod文件。同名冲突、个人修改、部分安装或未决动作保留并报告，不强制覆盖。

重新下载到新目录、移动目录或登记误指向父目录时，自动准备按EXE所在的项目目录恢复连接。核验本地安装账本或独立安装凭证、全部安装文件、游戏正常关闭及新旧目录无未决动作后，先备份配置和凭证，再接续原安装；需要时沿用冻结的Mod更新流程。配置修正本项目的command／cwd；已知1.0.x的11项工具清单可在相同保护下加入run_plan升级为12项，原有注释、其他工具、模型、额外环境和个人设置保留。自定义工具清单冲突仍停止。首次启用独立跟踪另加BALATRO_AGENT_REGISTRATION_FILE环境项。

独立资料位于Codex配置目录的balatro-agent/：installation.local.json记录项目归属、固定路径和安装哈希；checkpoint-executor.local.json与checkpoint-lifecycle.local.json在提交前保存未决意图，完成后才清除。准备与意图写入使用同一进程间锁；已加载服务校验归属、镜像和本地记录，迁移后的旧连接或过期连接不能覆盖未决操作。旧源码目录不可用时，只有独立凭证完整、镜像无未决动作且安装文件全部匹配才自动接续；同路径重新下载可按相同条件恢复丢失的本地账本。历史凭证保留在history/。

1.3.8起，启动／关闭完整收据同时保存到上述独立目录的lifecycle/项目路径哈希/，先保存独立副本再本地落盘。原目录重新下载后可恢复缺失的本地生命周期收据及其未决镜像，校验同一归属、记录哈希及执行检查点；不覆盖冲突内容，不读取存档，不执行游戏动作。原ID仍按原工具和相同参数查询；prepare只按明确COMPLETED／REJECTED收据补完检查点清理，INTENT／UNKNOWN不放行。未决状态在准备依赖前检查，详情显示区域和原ID。

旧版完整收据永久丢失时，只有经用户另行明确授权的人工封存可以解除失效等待：先核验游戏已停止、执行与输入检查点清晰、同一归属与原ID，逐字节归档独立原始文件，在同一安装锁内先保存永久UNKNOWN封存收据再解除该生命周期等待。独立retired-lifecycle/项目路径哈希/保存防重放标记；原ID查询继续返回UNKNOWN与retired=true，不重发、不证明原提交或成功。程序不自动创建封存标记或提供清理UNKNOWN入口。

旧目录中的动作记录、UNKNOWN和个人心得仍需保留；旧版仅有ID的独立镜像无法补回已删除的完整收据。显示“Original lifecycle receipt is missing”时，应从旧目录或已核验备份恢复runs/live/lifecycle/，不要重复解压、删除独立检查点或换ID重试。首次从无独立凭证的旧版本迁移仍需旧目录账本，或当前目录的完整已核验安装记录。无法证明来源、文件改动、镜像缺失／不一致、未决动作或TOML路径无法安全改写时停止，详情给出原因，不误报为网络超时。

由Codex执行或自定路径时，在源码根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Install -Automatic
```

需要先审查安装方案时，保留PowerShell两步模式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Apply
```

执行策略只作用于该进程，不改系统PATH或注册全局Python。实际安装须匹配冻结方案，游戏已正常关闭且无未决动作；拒绝覆盖已有Mod、注入器和同名MCP配置，保留其他设置及存档。方案在.artifacts/portable-plan.local.json，配置候选在portable-config-candidate.local.toml，真实收据在portable-install.local.json；成功须complete=true。部分失败保留收据和备份，不整份覆盖个人配置或删文件绕过。

路径不唯一时成对提供`-SteamDir "E:/Steam" -LibraryDir "F:/SteamLibrary"`；自定位置用`-ModsDir`、`-CodexConfig`。`-DependenciesOnly`只准备依赖；完整vendor包支持冷启动`-Offline`。`-Install`与`-Apply`不能混用。下载失败保留部分文件，不关闭证书校验。

默认配置Codex，模型登录由客户端负责。其他客户端可用`-CodexConfig "config/client-install.local.toml"`生成独立辅助文件，再按[客户端配置](model-client.md#客户端配置)接入；TOML不能直接导入Cline。首用两句提示见[首用提示](../../prompts/first-use.md)，模型操作规则见[bootstrap](../../prompts/bootstrap.md)。

## 已有安装与检查

已有安装再次打开Balatro Agent即可核验复用；命令行维护入口为scripts/project.py：

```powershell
.venv/Scripts/python.exe scripts/project.py status
.venv/Scripts/python.exe scripts/project.py prepare --reuse-only
.venv/Scripts/python.exe scripts/project.py diagnose --output runs/checks/diagnosis.json
.venv/Scripts/python.exe scripts/project.py build
.venv/Scripts/python.exe scripts/project.py build-launcher
.venv/Scripts/python.exe scripts/project.py verify-offline --output runs/checks/offline-preparation.json
.venv/Scripts/python.exe scripts/project.py update-mod --output runs/checks/mod-update-plan.json
.venv/Scripts/python.exe scripts/project.py check --output runs/checks/release-check.json
```

- status／diagnose只读核验安装、构建、进程、未决动作和日志元数据，不读局面或存档、不自动启闭游戏。
- prepare由自动入口调用，首次安装或更新仍冻结方案、核验备份并保留真实收据；--reuse-only只核验已有环境、枚举工具并保存本地准备结果，不下载安装。准备结果在.artifacts/onboarding.local.json；不代表Codex已加载工具或游戏已连接。
- build只重建项目内Mod，不安装。首次初始化已准备固定来源；新开发副本先运行bootstrap_sources.py。
- build-launcher仅用Windows内置.NET编译器重建Balatro Agent.exe与只开状态窗口的Balatro Status.exe；二者共享可审查源码，分别保存构建模式与哈希收据。既有EXE必须匹配收据，保留旧版后替换。不宣称旧编译器的输出字节可复现。源码打包只允许这两个绑定自有源码的EXE，其他运行程序仍排除。
- verify-offline仅复制公开交付文件，在无Python、venv和缓存的新目录以-DependenciesOnly／-Offline准备组件，核对版本、重建Mod并检查开发STDIO；不写真实游戏或客户端配置，不算其他机器完整首用通过。
- update-mod默认冻结差异；游戏正常关闭、无未决动作且已授权更新时，同一output加`--apply`。漂移拒绝，先核验备份，部分失败保留收据。
- check执行合成检查与隔离TEST开发STDIO，并冻结源码哈希；STDIO检查阻断真实游戏传输，不读取正在进行的局面。已有报告拒绝覆盖，应选择新output。默认同时核验记录中的安装，不匹配或不可读时可退出1；`--source-only`只以当前源码、固定组件和构建决定状态码，仍完整报告旧安装不匹配事实。须分别检查pytest_exit_code、development_stdio_exit_code、source_status_passed与recorded_installation_passed，不能把源码检查通过写成实装核验通过。

源码开发环境需要dev依赖；首次用户安装默认只装运行依赖：

```powershell
$env:UV_PYTHON_INSTALL_DIR = "$PWD/.tools/python"
.tools/uv/uv.exe sync --locked --python 3.13.11 --managed-python
```

部分检查提取本机合法游戏源码中的固定原生函数；私人材料不随仓库提供，缺失时这些检查跳过。公开快照、协议与其他合成检查仍执行，计数必须区分“通过”和“跳过”。

## 源码交付

```powershell
.venv/Scripts/python.exe scripts/project.py check --source-only --output runs/checks/release-check-1.3.4.json
.venv/Scripts/python.exe scripts/project.py package --check-report runs/checks/release-check-1.3.4.json --output deliverables/github-ready-1.3.4
.venv/Scripts/python.exe scripts/project.py verify-package --output runs/checks/source-validation-1.3.4.json
```

package要求本次源码检查、开发STDIO、内置固定发行包和最小Mod构建通过，源码哈希保持不变；不以历史游戏胜利作当前版本通过条件。它生成指定的deliverables/审核目录、deliverables/source/下的完整离线源码候选ZIP和逐文件清单，移除AGENTS中的本机操作者段落。自有EXE绑定可审查源码与构建收据，vendor只允许锁定的公开原始归档；不带本机运行环境、个人配置、游戏材料、存档、种子、TEST或备份。已有候选／review目录拒绝覆盖，先保全再重新构建。

示例版本须按实际pyproject版本替换，检查报告和审核目录均使用新路径。审核目录必须位于deliverables/内，不覆盖已有候选或Git历史。

verify-package在新目录用固定缓存离线初始化、重建Mod、核对全部候选文件哈希、运行公开检查和开发STDIO；公开副本缺少私人原生函数时按实际记录跳过。结果同时保留本机完整报告和源码包旁按版本命名的source-validation.json；source-manifest.json也按版本命名，旧版本附件保留。源码交付不证明当前版本真实游戏或其他电脑的完整首次安装。

公开候选的完整测试阶段允许300秒，其余阶段仍为120秒；超时保留阶段、部分输出和失败收据，停止后续阶段且不生成通过附件。这是开发核验预算，不改变游戏请求时限。准备替换候选前须保全已失败候选及报告。

GitHub提交审核目录中的内容，按本节源码交付检查核对允许文件。不要上传整个本机工作区；.gitignore排除本机环境和记录，但无法替代逐文件发布检查。公开发布／推送须取得用户授权，已有明确授权时按其范围执行。

## 运行保护与恢复

runs/live/中的动作检查点、历史UNKNOWN、生命周期记录，config中的本机配置，runs/checks/current-installation.json及.artifacts/backups/都是维护资料。保持原路径，不删作缓存。UNKNOWN只查询原ID和观察，按[恢复契约](reference.md#正常启动关闭与丢失会话)核验旧会话；不靠删文件、重启、更换ID或新开局绕过。

diagnose的process.state=not_found只表示当前调用进程看不到Balatro；Windows沙箱可能只展示沙箱内的进程，不能据此认定游戏已关闭。进程枚举失败报告unverified，正常枚举未找到报告not_found；实际连接与会话使用MCP health／observe核验，诊断本身不读取游戏信息或授权启动、关窗。

自动审批可因客户端网络错误在提交前中断。这与原生动作超时、项目日志写入失败分别调查；MCP超时设置不等于审批网络超时。保留客户端操作错误、原动作ID、项目意图与反馈记录；不关闭审批、改变destructive_hint或清除UNKNOWN来继续。短暂网络波动按[网络恢复](network-recovery.md)保留任务与只读等待；仅宿主确认未执行的审批超时可作一次原请求重试。[Codex自动审批说明](https://learn.chatgpt.com/docs/sandboxing/auto-review)、[MCP配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

Python本地HTTP修订由health的transport_policy="bounded-query-retry-v1"识别：默认超时、响应流及有限只读重试共用总预算；动作提交不重试。源码修改不表示已加载。客户端缺少MCP重载菜单时，可在保存本聊天检查点后由用户重启Codex；保持游戏窗口，不以重启游戏解除UNKNOWN。游戏Mod的翻面ready修订另需正常关窗、无未决动作、冻结哈希及备份后安装；当前要求保留窗口时只交付源码候选，不能热替换或冒称已实机验证。

安装恢复核对备份Manifest、原路径和哈希，只恢复必要文件，保留后来无关修改；不解码存档。工作区精简的私人归档位置、移动清单和核验结果由.artifacts/archive.latest.local.json指向。按清单恢复所需成员，不整体覆盖当前进度。

## 启动显示开关

默认隐藏启动控制台和加载画面，Lovely／Steamodded初始化、计时和日志仍保留。需要排障时可分别恢复：

```powershell
.venv/Scripts/python.exe scripts/project.py configure-display --console visible
.venv/Scripts/python.exe scripts/project.py configure-display --loading visible
```

偏好只写项目内config/startup-ui.local.json，示例见[配置](../../config/startup-ui.example.json)。随后正常关窗、核验无未决动作、build并按新冻结清单update-mod／--apply，下次正常启动生效。不得删除Lovely／Steamodded来隐藏外观；显示变化不代表已证明提速。

## 记录与经验

源码基线位于experience/experience/，运行时只读；游玩经验位于runs/local-experience/experience/，按主题优先读取。两层各自每主题仅一个current.md，本地更新提交完整修改后的正文并原子替换同一文件，不上传、提交或反写源码。原目录升级保留本地当前文件；换项目目录时先备份并逐文件核验，再单独迁移，不能复制动作检查点绕过UNKNOWN。已修订主题不自动混入新基线，未修订主题读取新基线；同主题不同正文的冲突须保留证据并复核。旧格式迁移先运行 `scripts/project.py experience-single` 查看计划，再用 `--apply` 逐文件核验归档并迁移，报告在runs/checks/，一次性归档在.artifacts/experience-archive/。已有MCP服务须重载后使用single-current-v2；不清锁或删记录来绕过未决写入。

用户明确授权将本地心得纳入源码时，运行 `scripts/project.py experience-promote` 预览；加 `--apply` 后先核验备份，再将本地当前文件原样整合到源码对应主题，并独立读回。原本地文件保留；源码独立变化且不兼容时拒绝覆盖。报告位于runs/checks/，备份位于.artifacts/experience-promotion/，均不随源码发布。该命令不自动提交或推送GitHub。

runs/live/run-plans/保存模型的短局内计划和全部修订，active.json绑定已确认新局/继续对局的公开作用域；升级时与运行记录一起保留，不作缓存清理，也不提交或上传。新局和公开档位/会话变化会使旧计划失效，文件仍保留。仅通过run_plan核对读回和同ID查询，不搬运作用域、清锁或删除记录来绕过未知动作。旧安装准备凭证只有11项工具时，新源码须重新枚举当前12项工具；源码修改并不说明客户端已经重载。

中文current.md仅包含攻略。默认MCP strategy读取不返回来源、历史案例或保存凭证；局后修订或核验时才显式读取content/full。两层各存储根的.metadata/experience/保留审计资料；备份与迁移必须包含整个经验根，不能只复制Markdown而遗漏元数据。

剪辑用按局JSONL/TXT位于runs/live/activity/by-run/，随runs/live/单独备份，不进入公开包。activity/active-run.json仅是可选日志当前记录游标；正常服务重载可以接续同一公开会话，断连空隙明确标记。损坏游标不自动删除，日志失败不改变原生执行、动作检查点或正常结果；原始会话活动文件继续保留。更新源码后重载MCP，核验health的per-run-v1标记启用按局保存。

历史精选记录集中于[evidence](../../evidence/README.md)，旧建设记录保留在私人归档，不作为当前任务或授权。新对局须按[bootstrap](../../prompts/bootstrap.md)先实际读取主攻略、核对条件，相关主题按需读取并保留全部反馈；终局有新认识才写入并独立读回。更新源码文件不代表客户端已重载：health缺少notes_policy="local-over-baseline-v1"、notes_write_scope="local_only"或notes_storage_format="single-current-v2"时，先重载MCP并重新核验，再提交心得。常规开发STDIO使用隔离目录和阻断游戏的传输；专项存储检查可以明确记录只读正式经验，不能混作当前Codex客户端已重载或游戏实机证据。

维护入口还提供timings／audit，基于完整过滤交付重算计时和记录一致性。调用间隔不是纯推理时间，故障恢复与连续正常局分开。
