# 网络波动与未执行审批超时 / Network recovery

短暂网络故障保留已授权任务、游戏窗口、原请求和原编号。当前聊天模型仍决定所有策略；客户端包装只负责调用、分类、查询和严格受限的恢复。

| 实际反馈 | 恢复方式 |
| --- | --- |
| 只读查询返回disconnected、request_timeout，或原编号查询返回transport_uncertain | 每批最多三次，批内退避250／500毫秒；仍失败时模型按10／20／30秒退避保留等待，每次等待最多30秒 |
| 宿主完整返回下面的未执行审批超时收据 | 先查原action_id、再实际观察；仅在记录缺失且同一会话、档位、ready观察均未变化时，原请求只重试一次 |
| 上述核验查询也断网 | 保留收据和冻结的原请求；恢复后再次通过callMcp调用完全相同的act请求，只接续核验，核验通过才使用尚未消耗的一次重试 |
| 原编号已有COMPLETED或提交前REJECTED记录 | 返回实际记录，不重发 |
| 完整宿主额度耗尽收据明确确认未执行 | 单独记录为NOT_SUBMITTED并保留原请求、完整宿主收据；不自动重试。解决额度故障或收到用户接续指导后，重新观察并按当前原生现场接续 |
| 已提交RUNNING／UNKNOWN、一般宿主错误或响应丢失 | 只查询原编号和观察，遵守原恢复契约 |
| 明确审批拒绝、会话／档位／观察冲突、必要持久化失败 | 保留原记录并报告阻塞，不能当作正常败局 |

唯一允许进入提交恢复分支的宿主收据是isError=true、structuredContent缺失或为null、只有一个文本块且全文为：

```text
The automatic permission approval review did not finish before its deadline. Do not assume the action is unsafe based on the timeout alone. You may retry once, or ask the user for guidance or explicit approval.
```

恢复依据是这份实际宿主收据；单独的record_not_found、缺少意图文件或相同快照都不证明请求未执行。[Codex自动审批说明](https://learn.chatgpt.com/docs/sandboxing/auto-review)区分审批超时与拒绝，并说明超时保持未执行。其他客户端若没有相同的可信未执行收据，只走原编号查询。

额度耗尽收据的完整宿主错误形状同上，首行只识别以下已实际取得的文案；单引号可为直引号或弯引号，重置时间可为合法12小时制时钟，其他文案变化保持UNKNOWN：

```text
Automatic approval review failed: Error running remote compact task: You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/settings/usage to purchase more credits or try again at 8:53 PM.
```

首行之后必须只有一个换行，再完整匹配：

```text
The action was not executed because automatic approval review could not be completed. This is a review failure, not a determination that the action is unsafe. Do not bypass the approval check; resolve the error or ask the user for guidance.
```

此收据只证明该次宿主调用未执行，不授予自动重试额度；仍返回原宿主错误，不伪装成服务端REJECTED。完整收据与原请求按动作ID留在宿主上下文，后续查询不能覆盖。一般错误、审批拒绝、游戏DTO中的相似文字或缺失记录均保持UNKNOWN。

客户端误分类可用 `restoreHostNonExecution(originalRequest, originalRaw)` 迁移，但待定记录必须是UNKNOWN，明确未进入审批超时重试、未消耗重试、没有待保存证据，并已保留该次实际调用的完整原请求和原宿主收据。调用参数必须与已保留内容全部一致，动作ID、完整observation_id及原会话均匹配，原收据本身须识别为上述未执行收据。真实服务DTO、RUNNING和缺字段旧状态均拒绝。旧客户端没有保留完整原调用时，先保全现状，从原实际工具交付进行独立人工核验；迁移函数不通过调用者提供的新材料自建证明。禁止合成收据、用新动作的错误解除旧动作或删服务端未决文件。迁移不调用游戏、不重放动作；随后核验原编号和新观察，由模型决定可见原生接续路径，不保证存在Continue。

UNKNOWN期间允许health、observe、wait_until_ready、read_notes和calculate等诊断，以及原编号查询／恢复。launch_game仍由服务端的持久化未决检查决定：可显示已有窗口，真实未决动作不得借此重启。其他写入及游戏推进继续阻塞。

重试保留action_id、observation_id、参数、依据及经验引用，在调用宿主前先按动作ID消耗一次额度；重试响应丢失时也不能再用首次收据提交。重试后收到额度未执行收据可以解除客户端门禁，但已消耗状态继续保留，手动再次调用同ID也不会恢复自动重试机会。重试仍经过宿主审批、MCP原生UI校验及档位保护。真正的服务UNKNOWN、第二次审批超时、审批明确拒绝和其他异常不会获得额外提交额度。持续网络波动不计为败局；模型保留等待并报告进度。无法按原记录恢复的真实UNKNOWN按原契约停止。

## 加载客户端包装

functions.exec首次使用时完整读取项目文件，将完整源码保存在宿主上下文。读取输出不得截断；实际项目根目录来自本次任务。

```javascript
const source = await tools.exec_command({
  cmd: 'Get-Content -Raw -LiteralPath prompts/mcp-evidence.js',
  workdir: actualProjectRoot,
  max_output_tokens: 12000
});
if (source.exit_code !== 0 || source.output.includes('Warning: truncated output'))
  throw Error('Read the complete helper before calling game tools');
store('balatro_mcp_helper_source', source.output);
```

每个exec调用重新从完整源码构造包装；各次实际观察、冻结请求和未决保护通过load／store保留：

```javascript
const callMcp = new Function('tools', 'load', 'store',
  load('balatro_mcp_helper_source') + '\nreturn callMcp;')(tools, load, store);
const raw = await callMcp('observe', {view: 'compact'});
store('last_raw', raw);
text(raw); // 先检查isError，再解码正常游戏DTO。
```

普通游玩无需登记证据即可使用callMcp。已登记的正式证据使用同一文件的recordMcp，逐次保存审批失败、原编号查询、观察与重试；失败查询的原UNKNOWN收据保留。宿主错误只进入固定的外部故障分类，不伪装成游戏DTO；完整宿主返回留在宿主上下文，避免将任意异常正文写入公开游戏日志。必要证据写盘失败时不继续核验或提交。

项目服务的act_submit仍只发送一次；这项恢复处理发生在宿主已明确未执行的MCP调用之前。源码检查与合成检查不证明代理线路已修复、客户端已重载或完整实机通关。

## English

Retain the authorized task, window, original request and action ID through transient network failures. The chat model remains the only strategy decision maker. The host helper retries read-only disconnected/request_timeout and original-ID transport_uncertain queries at most three times per batch, with 250/500 ms backoff. The model can continue original-ID queries and observations after 10/20/30-second waits, each bounded to 30 seconds.

Only the exact host error receipt above confirms that this approval invocation did not execute. Missing records or matching snapshots alone do not. callMcp checks the original record and a fresh ready observation in the same session and recognized profile before one identical retry, preserving the complete payload. If preflight queries fail, calling callMcp with the identical original request later resumes only these checks. The retry allowance is consumed before invoking the host, so a lost retry response cannot rearm it. Every retry still passes host approval and all native safeguards.

The separately recognized complete host usage-limit failure explicitly confirms non-execution. Only the captured two-line wording above, apostrophe variants and a valid 12-hour reset clock are accepted; unfamiliar wording remains UNKNOWN. Preserve the original request and raw host receipt as NOT_SUBMITTED, outside service DTOs; do not retry automatically. A consumed approval retry remains consumed for that action ID after a quota receipt. Resolve the quota failure or obtain user guidance, then refresh the native state. Migration requires a client UNKNOWN with a complete retained original request and receipt, an exact content/action/observation/session match, explicit unused retry flags and no pending evidence. Service DTOs, RUNNING and incomplete legacy state are rejected. Missing original delivery requires independent human audit; the migration helper cannot construct proof from replacement inputs. Read-only diagnostics remain available during genuine UNKNOWN. launch_game keeps the server's durable pending-action guard; no unknown action can authorize process restart or replay.

Submitted RUNNING/UNKNOWN, other host errors, lost responses, explicit denial, changed state or a second approval timeout receive no extra submission allowance. Keep querying the original ID and observing under the normal recovery contract; unresolved genuine UNKNOWN remains protected. Every evidence delivery is recorded separately, including the original UNKNOWN query, and required persistence failure stops further calls. This source change does not establish physical network recovery, client reload or a complete live-game result.
