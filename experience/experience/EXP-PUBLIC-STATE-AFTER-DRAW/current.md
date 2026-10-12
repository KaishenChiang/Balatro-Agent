# EXP-PUBLIC-STATE-AFTER-DRAW
<!-- 更新标记：5 -->

## 行动判断

- 稳定的COMPLETED观察可复用；身份、目标或控件缺失且影响下一动作时再observe。
- 拒绝后更新观察和参数再决策，不机械连发；UNKNOWN只查原ID，AWAITING_INPUT逐张处理后查原导航。

## 适用条件

- 零基位置仅属于当前观察；区分短暂翻牌与Boss长期背面。

## 反例与边界

- 额外observe不保证揭示身份或更快；ready不证明旧动作完成，禁止猜背面或重发UNKNOWN。

## 可信程度

中
