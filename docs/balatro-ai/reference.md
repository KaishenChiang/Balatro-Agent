# 技术参考

当前公开契约为reader-2／player-visible-1、executor-1、notes-1／calculate-1、run-plan-v1；观察展示可用columns-v1。适配版本与直接操作能力以实际health反馈为准。代码版本及实机覆盖以[PROJECT](../../PROJECT.md)为准，协议兼容不等于所有稀有分支都实测通过。

结构定义见 [观察Schema](observation-schema.json)、[动作Schema](action-schema.json)、[笔记Schema](notes-schema.json)、[计算Schema](calculation-schema.json)。Schema由scripts/export_contract.py从当前代码导出；行为组合以下文及双端校验为准。

observe、wait_until_ready、act、action_status的MCP参数view默认compact，full返回传统结构。compact只在较长同字段对象数组按列编码后更小时采用，反馈标记observation_encoding="columns-v1"。{$columns:[字段],$rows:[[值]]}按列一一对应原对象，可无损还原后按观察Schema解释；行号不是position，异字段对象不补null或合并。白名单过滤、背面/石头牌遮蔽、未知值与observation_id在展示压缩前确定。展示视图不参与动作去重身份，非法view在游戏读取/提交前拒绝；交付日志保留实际格式，内部确认继续使用完整白名单对象。

health声明public_changes_protocol="public-changes-v1"时，工具反馈可带顶层public_changes，以成功记录并实际交付的公开观察比较变化，完整观察保留。changed/unchanged/unknown只描述公开字段，不证明动作完成或授权继续UNKNOWN。历史收据不推进当前计划／观察／窗口目标，日志失败清除比较基线。详见[双语比较契约](public-changes.md)与[状态窗口](activity.md)。

## 观察与可见性

health的transport_policy="bounded-query-retry-v1"仅声明当前Python服务已加载本地传输修订，不证明游戏Mod或客户端审批网络已更新。本地请求总预算涵盖锁等待和响应流；未显式指定时沿用配置超时。仅health、reader_snapshot及原ID的action_status可在传输异常时限次重试，最多三次请求、50／100毫秒退避，共用原总时限；非法返回与协议错误不重试。act_submit永不重试，响应超时仍保留意图和UNKNOWN，不能推断未提交。

ready还检查已展示区域中牌的当前面与渲染面是否一致；翻面过渡返回processing，稳定背面牌仍保持遮蔽且不因此阻塞。不读取牌堆或等待原生长期保留的flipping标志，不将装饰动画或时间经过当作动作完成证明。

observe对应游戏原生love.update处理后，更新线程内的一次公开快照。Lua先做玩家信息投影，Python再按嵌套白名单严格校验与遮蔽；不拼接多次原始状态。health／observe／wait_until_ready均只读，可识别1–3任一实际档位；未知实际档位明确报错。0.6.2以current-native-v1策略直接使用当前档位，不依赖人工登记。动作从实际交付的观察取得档位，提交处连续核对档位和observation_id；执行中档位变化保持UNKNOWN。旧登记和证据保留。

| 字段 | 公开来源与范围 |
| --- | --- |
| schema_version／visibility_policy_version／profile | 固定契约与当前原生档位；未知档位不猜测 |
| observation_id／game_session | 公开状态与决策序号、非游戏时钟会话标识，不关联卡牌身份 |
| phase／underlying_phase | 已识别界面及初始化、计分、补牌或效果处理阶段；未知阶段unsupported |
| ready／ready_reason | 控制器锁、原生处理状态、当前区域与真实UI门槛；不证明某次动作完成 |
| resources | HUD公开金钱、得分、剩余出牌／弃牌、Ante／轮次及当前商店或包的公开资源 |
| setup／options | 当前显示牌组、注级、页面与候选，不提供隐藏解锁、未展示选择或种子 |
| preferences | 只在正常设置界面读取已显示的游戏速度 |
| regions | 已展示区域的容量、选择上限、卡牌与零基position；未展示对象可留下位置间隔 |
| blinds／tags | 当前盲注或当前三盲注选择栏的规则、要求、奖励及跳过标签，不提供未来盲注 |
| ui_actions | 当前实际绘制按钮、启用状态及公开目标；不调用can_*回调来试探结果 |
| menus | 已打开正常菜单可见的牌型等级、筹码／倍率、使用次数与牌组组成 |
| settlement_text／outcome | 当前已展示结算文字及正常终局UI确认的win／loss，不预测未显示收入 |
| unknowns | 固定缺项或省略标记，不回显内部字段、异常原文或栈 |

resources.availability为observed／unknown／not_applicable。null是未知或不适用，0只用于真实观察到的零；空数组须结合阶段和菜单范围解释，不能补成未观察过的事实。

正面牌只导出正常牌面及合法悬停文字。背面牌只保留position、visibility=face_down、selected，身份、点数、花色、说明、价格及身份性按钮在校验前移除，避免错误侧信道。石头牌rank／suit为空；真正未发现的对象只返回原生未知说明，不从内部key补名字。

正常牌组菜单提供公开多重集，聚合count与可见greyed状态，移除位置、选择和永久身份令牌，不包含抽牌排列；未打开菜单时没有组成详情。未开包、未展示商品和处理期间未确认展示的对象不导出。

悬停说明使用克隆接收对象生成原生提示，读取静态文字和DynaText当前字符串，随后清理临时对象；背面牌不生成提示。蓝图等只本地化公开兼容性，不模拟复制效果。Misprint可能读取未揭示牌堆，因此禁用其动态生成器并标记dynamic_tooltip_omitted；其他缺项标记tooltip_unavailable，不能当作无效果。

observe、动作返回、固定错误、变化摘要与模型可读日志采用同一投影。历史只含实际交付给模型的结果，等待中的轮询不补入历史。禁止原始完整状态、任意Lua、调试改值或存档回滚端点。

## 观察编号与就绪

编号为obs-<16位会话标识>-<公开决策序号>。公开投影、阶段、可操作门槛或动作提交变化使旧编号失效，合法无数值变化排序也不例外。隐藏状态、种子、RNG、内存地址和永久卡牌ID不参与编号。

COMPLETED中的观察是交付时快照；之后翻牌、节流或其他公开变化仍可能令其失效。duplicate响应携带原记录和原观察，不是新快照。稳定且目标仍明确时可复用；目标缺失、翻面、重排或提交前拒绝后重新observe并用新ID决策。

wait_until_ready的timeout_s默认10、范围0–30，只报告ready、timeout或明确问题。ready核对控制器、相关锁、STATE_COMPLETE、STOP_USE、拖动与实际UI；按钮需可见、启用、不被遮罩／禁用且符合原生节流。未知几何／容器保持保守边界。不等待无关装饰事件全部结束，不用固定睡眠或相同快照作为完成证明。

## 动作与参数

act(action, parameters, observation_id, action_id, reason, experience_refs)提交一个语义动作；action_status(action_id)只查询。未知动作、额外参数、重复目标、阶段／资源／容量／档位不符均拒绝。目标是当前观察的公开区域与零基位置。

| 动作 | parameters与范围 |
| --- | --- |
| select | region、positions；完整期望集合，保留强制选牌，全部核验后按差异原生点击 |
| sort_rank／sort_suit | {}；真实手牌排序按钮 |
| reorder | region、order；hand／jokers／consumables完整排列，保留原生禁拖与固定位置限制 |
| play／discard | {}操作已选牌；health声明positions-v1时可直接传完整positions，经原生点击与can_play／can_discard提交 |
| select_blind／skip_blind | blind_slot；只操作当前展示的盲注按钮 |
| buy／sell | region、position；同一动作内原生选中并点击当前实际按钮，核验资源、容量及资格 |
| use／buy_and_use | region、position；native-target-v1允许直接选中并使用，手牌目标仍由模型另行select |
| select_pack_card | region=pack、position；取普通／增强扑克牌或Joker；消费品须有当前明确显示且启用的取牌按钮 |
| reroll／cash_out／next_round／skip_pack | {}；当前真实按钮与相关效果 |
| open_run_setup／next_setup_page／previous_setup_page | {}；当前原生开局导航；新局请求允许替换未完成旧局 |
| select_setup_option | kind=deck或stake、position；当前已显示且正常解锁的原版候选 |
| next_setup_choices／previous_setup_choices | {}；当前牌组／注级候选列表分页，区别于设置阶段切页 |
| start_run／continue_run | {}；原生随机非挑战开局或继续，新局可原生替换旧局，未决动作与UNKNOWN仍阻断提交 |
| open_options／open_settings／next_game_speed／previous_game_speed | {}；正常选项／设置及原生0.5／1／2／4速度循环 |
| run_info／deck_info／close_menu | {}；当前正常菜单；自然解锁提示按单张close_menu处理 |
| main_menu／continue_endless | {}；原生终局导航；当前基线不执行无尽，另须授权 |

商店包打开和优惠券兑换按can_open／can_redeem映射buy，保留原生门槛。包内塔罗／星球／幻灵即用应提交use，手牌目标单独select；取牌和使用不能互换，程序不自动改成另一个语义。0.6.1在选中前拒绝只有使用按钮的消费品取牌请求；未知直接协议时按实际定义先选择公开目标。

Continue页已渲染且next_setup_page启用的“新的一局”可原生切页。新局按钮已显示且启用时可按用户新局请求原生替换旧局；不再读取旧局won标志作为前提，不解码或删存档。观察、原生档位、设置解锁、随机非挑战和未决动作检查仍适用。用户可明确指定原版牌组与固定注级、最高已解锁注级或爬塔；先核验所选牌组，再核对其当前公开注级候选，锁定或无法确认时停止，不强制解锁。

固定注级与最高已解锁注级只尝试一局。明确爬塔授权后，从该牌组最高已解锁注级开始，正常失败先报告再重试当前注级；获胜后重新核验原生解锁，按白／红／绿／黑／蓝／紫／橙／金紧接升一级，直至金注通关或用户叫停。每局保留失败与经验收据；故障和UNKNOWN不能计作正常败局或触发自动重试。必要新局导航仍使用当前观察下的原生动作，本次目标局开始后不自行中途重开。

observe／wait_until_ready成功返回的server_time={utc,unix_s}是服务端墙钟元数据，不属于游戏观察或observation_id。单局时长采用开局提交前的observe至终局确认后observe的时间差，包括客户端决策与执行等待，不代表纯推理时间。缺起点、旧服务无时钟或时钟倒退时用时未确认。每局简短报告实际牌组、注级、胜负、底注／回合、时长与心得是否更新；“已更新”须有本局成功写入且read_notes读回确认，无新增可报告未更新。

## 去重、完成与不确定性

先落盘安全意图，RECEIVED→RUNNING→COMPLETED；提交前失败REJECTED，提交后异常／失联／超时为UNKNOWN并阻止新动作。同ID同规范内容返回已有记录，同ID不同内容id_conflict。reason也属于内容；参数键、选牌集合与经验引用规范化，reorder.order保留给定顺序。REJECTED的ID同样保留，修正后用新ID。submitted=true描述原记录，不证明又执行了一次；丢失／未知记录为null。

提交在游戏更新线程连续核验并走原生操作；只跟踪本次回调、其相关事件及派生事件，不等全局队列清空。相关事件被取消保持UNKNOWN，不能当成完成。

| 组别 | 完成证据 |
| --- | --- |
| select／reorder／sort | 原生调用／回调、相关事件、期望集合／排列和可操作UI |
| 盲注、结算、商店、菜单导航 | 原生回调、相关转换与公开下一决策点 |
| play | 回调且经过HAND_PLAYED，补牌回hand、结算或正常终局 |
| discard | 原生弃牌、DRAW_TO_HAND补牌及hand可操作 |
| buy／sell／reroll／use／取牌 | 原生交易／效果及相关事件完成、正常下一阶段；免费、零分或同商品不要求数值必变 |
| buy包 | 包内容已实际展示，初始化及相关事件完成 |

正常win／loss可能暂停剩余事件：仅在出牌回调、HAND_PLAYED和终局UI确认都满足时允许terminal_confirmation，related_events_complete=false如实保留，不清队列或改计分。HTTP成功、ready、扣款或按钮点击本身不是完成证明。

Python请求等待上限20秒，游戏相关动作上限60秒；Python超时不取消游戏操作。RUNNING查原ID，UNKNOWN或响应丢失后只action_status／observe，不重发或继续下一动作。游戏记录之后确实完成才据证据恢复。意图日志失败不提交；提交后日志失败保持不明。目标准备事件只在游戏端记录已UNKNOWN时停止迟后点击，不能声称Python超时已取消动作。

文件写入失败可带io_failure={stage,errno,winerror}，仅输出固定阶段和白名单数字错误码，未知码为null，不回显异常文字、路径或栈。它帮助区分意图、反馈、检查点及交付写入故障，不改变REJECTED／UNKNOWN、提交标记或恢复条件。历史日志没有这些错误码时，不能补猜具体写盘原因。

Windows文件打开遇共享／锁冲突，或CRT仅返回EACCES时，最多尝试4次，退避延迟累计170毫秒（不包含文件操作本身耗时）；检查点替换只重试同一已准备文件，源文件消失即停止。已经打开后的write／flush／fsync、进程间锁获取、游戏请求和原UNKNOWN动作均不重试；持续错误仍按原保护拒绝或保持不明，不改权限或清记录。

客户端的isError或自动审批中断可能发生在MCP处理器收到请求之前，属于外部调用故障。先保留完整工具返回，不假定structuredContent总存在；isError=true时不得将content中的JSON误作成功游戏反馈。原动作仍查原ID及观察，缺少意图或record_not_found不能单独解除不确定性。仅宿主完整审批超时收据确认本次请求未执行时，客户端callMcp可在核验原记录及同一ready观察、会话和档位后原样重试一次；普通错误、明确拒绝或真实UNKNOWN均不适用。详见[网络恢复](network-recovery.md)。

AWAITING_INPUT/native_unlock_input仅适用于已确认导航回调产生的当前真实解锁提示，保留原pending。重新observe，用新ID单次close_menu后查原导航；每张提示独立处理，最多一条input_pending，不连点或重新提交导航。

recover_lost_session在旧会话确实丢失、当前原记录仍缺失、当前档位已知且观察新鲜可操作时，归档本地待定意图。审批层中断而没有本地意图时，仅在全部检查点清晰、服务曾在唯一旧会话实际交付该ID的UNKNOWN／record_not_found且没有同ID意图或已提交／正常结果时，可按该交付历史归档；同会话缺失、历史不明或歧义、其他未决动作仍拒绝。它不证明原动作未提交，原结果仍UNKNOWN，不重发、不计正常败局，不读取存档或替模型选择下一动作。

## 正常启动、关闭与丢失会话

launch_game(operation_id, timeout_s=25)未运行时核验Steam并正常启动固定AppID2379780；已运行只核验并请求显示已有窗口，不重复启动或点击。每局结算先保存并读回心得、通知基础信息与结果；默认单局或爬塔完成后停留结算页面并保留窗口。仅明确爬塔授权允许本局报告后的正常下一局导航，所有模式不自动关窗。只有用户另行明确要求关闭游戏时，模型才调用close_game(operation_id, observation_id, timeout_s=15)；它只允许已识别当前档位、匹配观察、ready、正常终局或无当前对局主菜单、无未决动作，以正常WM_CLOSE确认进程停止，不强杀。

同operation_id同参数读取持久记录；UNKNOWN或超时不换ID重做。游戏动作UNKNOWN时仅可显示已运行窗口，不能新启动或关闭。焦点未确认与进程状态分开报告，正常关窗不证明磁盘所有数据全部落盘。

游戏重启会丢失去重记录，不能承诺跨进程恰好一次。recover_lost_session(action_id, observation_id, recovery_id)先要求实际查询与观察确认不同会话、已识别当前档位、ready及原ID UNKNOWN/record_not_found；服务再次核对原ID、观察和检查点，先原子保存退役收据再解除失效等待。同会话、断连、未知档位或新冲突均拒绝。

RETIRED只代表封存成功，original_action_state=UNKNOWN、normal_game_completed=false、game_action_submitted=false保留；不点击游戏或重发动作。同recovery_id同参数读取持久收据，不同参数拒绝。响应丢失只同ID查询；确认封存后重新观察，再由模型决定下一步。记录位于runs/live/executor/及runs/live/lifecycle/，不是缓存。

## 经验与公开计算

read_notes(kind="experience", note_ids=null, revision=null, view="strategy", query=null, offset=0)实际读盘；开局指定note_ids=["EXP-GENERAL-GUIDE"]，其他主题按当前条件读取。主攻略不存在时才省略note_ids读取可用正式经验；省略仍兼容读取全部，[]返回空。正式经验每个主题只有一个current.md；revision是更新计数，指定旧计数返回not_found，TEST仍支持历史读取。MCP默认strategy只返回行动判断、适用条件、反例、可信程度和简短更新引用，不返回来源编号、历史案例、时间或写入凭证。显式content/full用于审计，full额外返回中文攻略Markdown。新聊天或压缩后引用不清时重读，笔记只改变可读取上下文，不改变模型参数。

view="index"只返回note_id、revision/current_revision、note_ref、confidence与最多120字符的行动/条件/反例预览（正式经验用rule_preview，TEST保留fact_preview），明确discovery_only/preview_only。query为最多80字符的不区分大小写字面子串，匹配编号与策略正文，不搜索审计资料、不排序推荐动作或生成摘要；offset与next_offset按20条分页，索引可扫描最多200个主题。索引不算完整经验读取，先strategy读选中主题再作依据。query和非零offset仅index允许；索引仍每次读盘、校验完整记录，不走过期缓存。

write_note(note_id, content, expected_revision, write_id, kind="experience")创建expected_revision=0，更新必须匹配当前修订。EXP-／TEST-编号与分区匹配，仅大写字母、数字、连字符。content含sources(run_id、steps)、facts、interpretation、conditions、counterexamples、confidence(low／medium／high)、revision_reason。模型撰写策略解释，程序校验结构；来源真实性须对照实际交付。

write_note的MCP返回也默认view="strategy"；显式content/full用于核对审计内容，full包含Markdown。展示视图不进入写入去重身份，不改变持久化及读回要求。更新前的完整结构可在局后需要修订时显式读取，不在每步游玩时加载来源与历史案例。

正式基线目录experience/experience/只读；个人经验目录runs/local-experience/experience/优先读取，TEST独立且不继承基线。首次本地修改读取当前基线并由模型增改，提交完整正文，只创建本地current.md，不复制旧版本。后续更新直接原子替换同一路径。源码升级后已修改主题保留本地当前内容，不自动拼接新基线；未修改主题跟随基线。日常本地经验不自动上传、提交或反写源码。旧布局由scripts/project.py experience-single先预览，再以--apply逐项归档、核验和迁移；原始对局记录与UNKNOWN不在迁移范围。

current.md只显示中文攻略，不嵌入重复JSON正文、来源清单或保存时间；一个简短中文更新标记用于绑定提交。审计资料另存各存储根的.metadata/experience/<note_id>.json，仅含当前来源/案例、修订理由与简短写入凭证，不复制策略正文。先原子落盘旧/新元数据候选，再原子替换Markdown作为提交点；读盘只选择Markdown哈希匹配的候选，失败写入不能覆盖旧策略或把未提交意图当完成。成功后精简为一份元数据，精简暂时失败不影响已提交正文，后续读取仍按哈希核验。同写ID同内容去重、异内容拒绝，旧请求不会覆盖当前内容；旧确认可用原样请求和已存哈希重建，不等于旧正文仍可读。禁止穿越、绝对路径、符号链接／联接、reparse点、设备或流名称；残留锁报busy，不自动删除。写入后实际读回、独立进程验证。写入前health须声明primary_experience_note="EXP-GENERAL-GUIDE"、notes_policy="local-over-baseline-v1"、notes_write_scope="local_only"、notes_storage_format="single-current-v2"；缺标记先重载再核验。跨构筑规则更新主攻略，特定技巧保持简短，无新认识不强行新增流水账。

每类最多200笔记、每条100次更新计数（TEST保留历史文件）、每次读20条；字段最多2000字符、结构12000 UTF-8字节、单文件65536字节、单次返回262144字节。sources最多20项，各1–5000的步骤最多50个。提交后日志失败返回write_state=UNKNOWN，按同write_id恢复，不能猜测未写入。固定安全错误不回显路径、任意输入或栈。

calculate只处理显式输入：sum／difference／product／quotient／mean／median／variance_population用values，difference／quotient仅两数；combination用n、k；hypergeometric用population、successes、draws、min_successes、max_successes。返回规范输入、公式、结果与假设，不读取游戏、种子、存档或网络。

最多200个有限数、绝对值≤10^12，组合／概率总体≤1000，结果绝对值≤10^100；拒绝未知、null、bool、NaN／Infinity、除零及额外字段。概率前提由模型依据公开信息确认；没有推荐动作、未来模拟或任意代码功能。

## 局内计划

run_plan(mode="read")实际读取当前局计划；mode="write"需最新实际交付observation_id、content、expected_revision和write_id，Schema见[计划写入](run-plan-schema.json)。content含objective、priorities、recheck_when、experience_refs，正文最多2000 UTF-8字节；每项最多200字符，优先事项与复查条件各1–4项，引用最多6个EXP-XXX@rN，须先成功content/full读取对应版本。首次修订0，本局最多50次修订；同ID同内容查询已提交版本，不同内容拒绝，当前修订冲突拒绝。新聊天/压缩后恢复计划并重读引用不清的经验。MCP进程重启须先以未改变的公开观察确认连续性，无法确认时不复用旧计划。

只对已确认start_run/continue_run的当前原生局建立公开作用域；写入绑定最近实际交付且ready的hand/shop/pack/blind_select观察，终局、未决动作或检查点故障拒绝新修订。新局、进入开局设置/主菜单、档位/会话变化或公开轮次回退使旧计划失效，保留旧文件与所有修订。计划位于runs/live/run-plans/，不上传、不作为动作授权或真实事实证据；程序不生成正文或策略，不自动执行计划。计划故障单独返回，不改变原生动作完成状态，详情见[优化说明](optimization.md)。

## 证据与评测

首版A–F包括安装连接、行为／失败路径、两正常自主局、经验跨局读写／修订、阶段覆盖和交付材料。已通过的历史与当前版本边界见[PROJECT](../../PROJECT.md)及结构化报告；旧结果不替代新版本验证，稀有未遇分支不冒称覆盖。

比较前登记模型／客户端／推理设置、版本、硬件、牌组／注级、正常解锁基线、游戏速度、尝试预算、超时、停止规则和经验起点。空经验、冻结经验、逐局学习分别报告。保留全部正常胜负、拒绝、故障、UNKNOWN和技术人工帮助；一个实例只有一个操作模型。

墙钟、工具等待、原生完成耗时和调用间隔分开；纯模型推理未知，不能用差值冒充网络或推理时间。单局胜利、不同随机局面和调用减少都不证明稳定胜率、模型排名或固定速度倍数。不中断首次接入成绩不能由故障恢复补成。

固定来源与许可见[依赖锁](../../config/dependencies.lock.json)、[NOTICE](../../third_party/NOTICE.md)；正常安装与备份恢复见[维护说明](maintenance.md)。原版私有源码只用于本机来源核验，不公开分发。
