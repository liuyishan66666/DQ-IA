# ProVerif 2.05 首次有效查询：阶段性解读

以下依据用户提供的 Ubuntu 终端 RESULT 行解读，尚未收到并核对完整日志和模型摘要，不作为完整的最终验证报告。
模型版本对应修复 `expand` 保留字后的版本；当前修复只涉及结果解析，不修改 `.pv` 模型或查询。

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

## 下一步需要的证据

用户提供的 bounded_secure 日志最后 120 行是 `accepted_both` 可达性的合法执行轨迹，不是单射查询对应的无法证明原因。
需要完整的 `.log` 和原 `validation.json`，定位该查询的推导、轨迹重建及近似提示，才能区分建模问题、工具近似限制或真实反例。
在诊断完成前不修改防重放规则、事件参数或攻击者能力以追求 TRUE。

已有日志可重新解析，无需重跑 ProVerif，也不覆盖原始证据：

```bash
python3 -m experiments.proverif.reparse \
  experiments/proverif/results_ubuntu_02 \
  --output experiments/proverif/results_ubuntu_02_reparsed
```

重解析会先检查当前 `.pv` 摘要及查询预期是否与原记录一致，逐字节保留日志，注明未重新执行 ProVerif；未解决的单射查询仍返回 `needs_investigation`。
