# Balatro Agent

[English](README.md) | 简体中文

**让AI接手下一局《Balatro／小丑牌》。**

支持工具调用的AI通过本地MCP读取玩家可见信息、决定并执行游戏操作，在对局中保存和复用心得。

适用于 **Windows x64 · Steam版Balatro · Codex桌面应用**。启动器和游玩状态窗口支持中文、英文。

## 下载与开始使用

1. **[下载完整项目ZIP](https://github.com/KaishenChiang/balatro-agent/archive/refs/heads/main.zip)**，解压到可长期保留的目录，保留整个文件夹。先安装Steam版Balatro并登录Codex；首次安装或更新前正常关闭游戏。
2. 打开 **[Balatro Agent.exe](<Balatro Agent.exe>)**，等待“准备就绪”。程序自动识别项目路径，查找游戏、准备依赖、备份并安装Mod、配置MCP，无须另装Python。
3. 选择“牌组”和“注级／模式”，点击 **“在 Codex 中开始”**。Codex支持项目链接时，会打开对应项目的新聊天并填好提示；在Codex确认并发送即可开始。启动器成功发出打开请求后自动关闭。

若项目链接未打开，重新打开启动器，点击 **“复制游玩提示”**，粘贴到已加载`balatro-agent`工具的Codex本地聊天。提示包含实际项目路径和当前选择，无须先手动选择项目文件夹。首次配置后看不到工具时，重载MCP或重新打开Codex。

启动器默认跟随Windows显示语言，可通过“Language / 语言”切换。发送提示后可以关闭启动器，保留项目文件夹即可。

## 实时游玩状态

MCP启动游戏时同步打开独立状态窗口，以 **时:分:秒** 显示阶段变化、简短决策、计划更新、操作结果和心得保存状态。窗口展示模型已提交的依据与计划。

窗口可随时关闭，不影响游玩；运行 `Balatro Agent.exe --monitor` 可重开。[窗口机制与实测开销](docs/balatro-ai/activity.md)

## 牌组与注级

默认红色牌组／白注。可选 **15种原版牌组**；是否解锁在游戏内核验，未解锁或无法确认时通知并停止。

| 注级／模式 | 游玩方式 |
| --- | --- |
| 白、红、绿、黑、蓝、紫、橙、金注 | 使用所选等级，只尝试一局 |
| 最高注级 | 使用该牌组当前已解锁的最高等级，只尝试一局 |
| 爬塔模式 | 从该牌组最高已解锁注级开始；正常失败重试，获胜后核验并升一级，直到金注通关或您叫停 |

爬塔每局先报告并复盘，再继续下一局。连接故障或结果不明时先恢复，不当作败局重试。

## 结算与心得

每局结束返回简短报告：**实际牌组／注级 · 胜负 · 底注／回合 · 用时 · 心得更新状态**。

单局结束或爬塔完成后，**停留结算页面，保留游戏窗口**。爬塔在每局报告后继续。

AI开局先读取[主攻略](experience/README.md)，相关主题按需读取；新心得保存在本机 `runs/local-experience/`，不会自动上传。移动或重新下载项目时，请单独备份和迁移该目录。

## 更多说明

[维护与恢复](docs/balatro-ai/maintenance.md) · [英语适配](docs/balatro-ai/english-support.md) · [游玩规则](prompts/bootstrap.md) · [开发与验证](PROJECT.md) · [更新记录](CHANGELOG.md)

如果这个项目对您有帮助，欢迎点一个 **Star**；遇到问题请提 [Issue](https://github.com/KaishenChiang/balatro-agent/issues)。

## 许可

自有代码、文档和经验采用[MIT许可](LICENSE)，第三方许可见[NOTICE](third_party/NOTICE.md)。
