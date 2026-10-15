# Balatro Agent

[English](README.md) | 简体中文

**让AI接手下一局《Balatro／小丑牌》。**

支持工具调用的AI通过本地MCP读取玩家可见信息、决定并执行游戏操作，在对局中保存和复用心得。

适用于 **Windows x64 · Steam版Balatro · Codex桌面应用**。启动器和游玩状态窗口支持中文、英文。

## 金注通关

**GPT-6.1 Sol 已通过本项目完成蓝色牌组／金注通关。** 下方可直接播放26秒实机节选（等待段已加速）。

https://github.com/user-attachments/assets/fbc3b384-bd33-472a-82f0-dbf9969bc187

[下载MP4原片](https://github.com/KaishenChiang/Balatro-Agent/releases/download/v1.4.0/gold-stake-win.mp4)

## 下载与开始使用

1. **[下载v1.4.0完整项目ZIP](https://github.com/KaishenChiang/Balatro-Agent/releases/download/v1.4.0/balatro-agent-1.4.0-source-candidate.zip)**，解压到可长期保留的目录，保留整个文件夹。先安装Steam版Balatro并登录Codex；首次安装或更新前正常关闭游戏。
2. 打开 **[Balatro Agent.exe](<Balatro Agent.exe>)**，等待“准备就绪”。程序自动识别项目路径，查找游戏、准备依赖、备份并安装Mod、配置MCP，无须另装Python。
3. 选择“牌组”和“注级／模式”，点击 **“在 Codex 中开始”**。Codex支持项目链接时，会打开对应项目的新聊天并填好提示；在Codex确认并发送即可开始。启动器成功发出打开请求后自动关闭。

若项目链接未打开，重新打开启动器，点击 **“复制游玩提示”**，粘贴到已加载`balatro-agent`工具的Codex本地聊天。复制与项目链接共用短提示，包含实际项目路径、当前选择及操作规则文件入口，无须先手动选择项目文件夹。首次配置后看不到工具时，重载MCP或重新打开Codex。

启动器默认跟随Windows显示语言，可通过“Language / 语言”切换。发送提示后可以关闭启动器，保留项目文件夹即可。

上一会话操作未确认、收据丢失或检查点异常时，正常退出游戏，在启动器错误页点击 **“放弃旧会话并重新准备”**。旧记录保留，旧动作不重放，完成后可重新开始；封存中途退出也可重新打开启动器接续。[恢复说明](docs/balatro-ai/maintenance.md#运行保护与恢复)

## 通过CC Switch测试其他模型

使用 [**CC Switch**](https://github.com/farion1231/cc-switch) 在Codex中配置其他模型服务，继续使用本项目的本地MCP工具和 [**Balatro Agent.exe**](https://github.com/KaishenChiang/Balatro-Agent/blob/main/Balatro%20Agent.exe)。**已通过CC Switch成功接入DeepSeek V4.1 Flash并进行本项目游玩。**

## 实时游玩状态

MCP启动游戏时同步打开独立状态窗口，以 **时:分:秒** 显示阶段变化、简短决策、计划更新、操作结果和心得保存状态。窗口展示模型已提交的依据与计划。

窗口可随时关闭，不影响游玩；双击 **[Balatro Status.exe](<Balatro Status.exe>)** 即可重开，也可运行 `Balatro Agent.exe --monitor`。[窗口机制与实测开销](docs/balatro-ai/activity.md)

每局活动自动保存在 `runs/live/activity/by-run/`。正常结算会记录胜负及到达底注/回合，局后心得更新也保留。

## 牌组与注级

默认红色牌组／白注。可选 **15种原版牌组**；所选牌组须在游戏内确认已解锁。发送游玩提示后，模型先打开或显示游戏，再核验连接。

| 注级／模式 | 游玩方式 |
| --- | --- |
| 白、红、绿、黑、蓝、紫、橙、金注 | 使用所选等级，只尝试一局 |
| 最高注级 | 使用该牌组当前已解锁的最高等级，只尝试一局 |
| 爬塔模式 | 从该牌组最高已解锁注级开始；正常失败重试，获胜后核验并升一级，直到金注通关或您叫停 |

爬塔每局先报告并复盘，再继续下一局。

## 结算与心得

每局结束返回简短报告：**实际牌组／注级 · 胜负 · 底注／回合 · 用时 · 心得更新状态**。

单局结束或爬塔完成后，**停留结算页面，保留游戏窗口**。爬塔在每局报告后继续。

AI开局先读取[主攻略](experience/README.md)，相关主题按需读取。源码基线与本地经验各自每主题只保留一个 `current.md`；本地更新在原正文上增改，再原子替换同一文件。本地同主题优先，保存在 `runs/local-experience/`。

## 更多说明

[维护与恢复](docs/balatro-ai/maintenance.md) · [英语适配](docs/balatro-ai/english-support.md) · [游玩规则](prompts/bootstrap.md) · [验证证据](evidence/README.md) · [更新记录](CHANGELOG.md)

## 许可

自有代码、文档和经验采用[MIT许可](LICENSE)，第三方许可见[NOTICE](third_party/NOTICE.md)。
