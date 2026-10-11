# 网络波动与未执行审批超时 / Network recovery

短暂网络故障保留已授权任务、游戏窗口、原请求和原编号。当前聊天模型仍决定所有策略；客户端包装只负责调用、分类、查询和严格受限的恢复。

| 实际反馈 | 恢复方式 |
| --- | --- |
| 只读查询返回disconnected、request_timeout，或原编号查询返回transport_uncertain | 每批最多三次，批内退避250／500毫秒；仍失败时模型按10／20／30秒退避保留等待，每次等待最多30秒 |
| 宿主完整返回下面的未执行审批超时收据 | 先查原action_id、再实际观察；仅在记录缺失且同一会话、档位、ready观察均未变化时，原请求只重试一次 |
| 上述核验查询也断网 | 保留收据和冻结的原请求；恢复后再次通过callMcp调用完全相同的act请求，只接续核验，核验通过才使用尚未消耗的一次重试 |
| 原编号已有COMPLETED或提交前REJECTED记录 | 返回实际记录，不重发 |
| 已提交RUNNING／UNKNOWN、一般宿主错误或响应丢失 | 只查询原编号和观察，遵守原恢复契约 |
| 明确审批拒绝、会话／档位／观察冲突、必要持久化失败 | 保留原记录并报告阻塞，不能当作正常败局 |

唯一允许进入提交恢复分支的宿主收据是isError=true、structuredContent缺失或为null、只有一个文本块且全文为：

```text
The automatic permission approval review did not finish before its deadline. Do not assume the action is unsafe based on the timeout alone. You may retry once, or ask the user for guidance or explicit approval.
```

恢复依据是这份实际宿主收据；单独的record_not_found、缺少意图文件或相同快照都不证明请求未执行。[Codex自动审批说明](https://learn.chatgpt.com/docs/sandboxing/auto-review)区分审批超时与拒绝，并说明超时保持未执行。其他客户端若没有相同的可信未执行收据，只走原编号查询。

重试保留action_id、observation_id、参数、依据及经验引用，在调用宿主前先消耗一次额度；重试响应丢失时也不能再用首次收据提交。重试仍经过宿主审批、MCP原生UI校验及档位保护。真正的服务UNKNOWN、第二次审批超时、审批明确拒绝和其他异常不会获得额外提交额度。持续网络波动不计为败局；模型保留等待并报告进度。无法按原记录恢复的真实UNKNOWN按原契约停止。

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

Submitted RUNNING/UNKNOWN, other host errors, lost responses, explicit denial, changed state or a second approval timeout receive no extra submission allowance. Keep querying the original ID and observing under the normal recovery contract; unresolved genuine UNKNOWN remains protected. Every evidence delivery is recorded separately, including the original UNKNOWN query, and required persistence failure stops further calls. This source change does not establish physical network recovery, client reload or a complete live-game result.
