# ProVerif 2.05 首次有效查询：阶段性解读

已收到用户上传的完整 Ubuntu 日志包，核对了 5 个模型 SHA-256，并使用修复后的解析器重新读取原始日志；未重新执行 ProVerif。
模型版本对应修复 `expand` 保留字后的 baseline 版本，所有 baseline 文件及查询保持不变。原始包、原 JSON、重新解析结果和模型快照见 [证据目录](evidence/ubuntu2204-run02/README.md)。

|模型|秘密性|非单射来源认证|单射认证|接受可达|
|---|---|---|---|---|
|bounded_secure|TRUE|TRUE|无法证明|是，两条指令均可接受|
|bounded_no_replay|TRUE|TRUE|无法证明|是，两条指令均可接受|
|bounded_root_leak|TRUE|FALSE|FALSE|是，两条指令均可接受|
|bounded_kem_key_leak|FALSE|TRUE|无法证明|是，两条指令均可接受|
|unbounded_core|TRUE|TRUE|FALSE|是|

这些输出表明工具已完成查询，不再是语法解析失败。正常模型的秘密性和非单射认证成立；根密钥泄露会破坏来源认证，KEM 私钥泄露会破坏命令秘密性；不含防重放状态的无界核心存在单射性质反例。
所有结论只针对已定义的符号抽象、给定上下文及相应有限/无界范围，不扩展为计算安全或完整实现证明。

三个有限模型的单射查询仍为 `cannot be proved`，必须保留为未解决；不能自动解释为 TRUE、FALSE、已发现攻击或已确定的工具近似误报。
去掉重放检查的有限对照也没有重建出该性质的反例，故有限状态这一部分尚未完成，不能仅凭其他查询正确就称全部验证通过。

## 已定位的运行器问题

ProVerif 2.05 在单射查询之后补充输出：

```text
RESULT (but event(...) ==> event(...) is true.)
RESULT (even event(...) ==> event(...) is false.)
```

它们描述较弱的非单射对应，是说明行，不是新的独立查询。旧解析器错误地将它们当作结果，并因尾部括号误判为未知，从而和已有非单射结果冲突，清空解析字典。
新解析器忽略这些明确的补充说明，保留独立 RESULT 行，仍严格将 `cannot be proved` 记为未知。9 项核对器测试覆盖了用户提供的实际格式。
这项修复不能解决有限状态的单射查询，也不会修改该查询预期值来制造成功。

## 完整日志中的诊断与后续实验

bounded_secure 原日志 7158–7162 行显示：同一个输入动作上合并的消息无法统一或使约束为假，工具建议 `Try adding a [precise] option on it.`，随后报告 `Could not find a trace corresponding to this derivation.`。
bounded_no_replay 和 bounded_kem_key_leak 也有同类提示，见 [诊断摘录](evidence/ubuntu2204-run02/diagnostic_excerpt.txt)。
因此，这次候选推导未能重建为可执行攻击，不能把它称作已确认的重放攻击；同样不能因此宣称单射性质成立。

新增 `models_precise/` 作为显式对照：仅把接收动作改为 `in(net,wire:bitstring) [precise];`，按工具建议更精确地跟踪输入。
已逐字比较：去掉该输入选项后，5 个模型分别与原 baseline 完全一致；所有安全查询、预期值、防重放规则、泄露条件和攻击者能力均未改变。
默认仍运行 baseline；必须显式使用 `--variant precise` 才运行新版本。新版本尚待用户 ProVerif 2.05 实际执行，不能预填其结果。

```bash
python3 -m experiments.proverif.run \
  --variant precise \
  --proverif /home/liuyishan/.opam/default/bin/proverif \
  --output experiments/proverif/results_precise_ubuntu_01
```

如果仍无法证明，继续记录未解决状态；即使有限模型得到 TRUE，也只适用于两序列/三接收尝试的抽象，不能扩展为完整滑动窗口实现的证明。

已有日志可重新解析，无需重跑 ProVerif，也不覆盖原始证据：

```bash
python3 -m experiments.proverif.reparse \
  experiments/proverif/results_ubuntu_02 \
  --output experiments/proverif/results_ubuntu_02_reparsed
```

重解析会先检查当前 `.pv` 摘要及查询预期是否与原记录一致，逐字节保留日志，注明未重新执行 ProVerif；未解决的单射查询仍返回 `needs_investigation`。
