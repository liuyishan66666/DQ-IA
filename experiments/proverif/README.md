# ProVerif 2.05 符号验证实验

本目录提供 DQ-IA 第 5 节的符号模型和运行器，针对用户已有的 ProVerif 2.05。
它与已经完成的真实密码协议测试、网络仿真分别报告。

**当前状态：用户已在 ProVerif 2.05 得到实际查询结果，但部分有限状态单射查询无法证明，验证尚未全部完成。** 见 [阶段性结果与未解决事项](PROGRESS.md)。
云环境没有 ProVerif，官方下载请求返回代理 403，无法独立在云端运行。用户 Ubuntu 存在 `/home/liuyishan/.opam/default/bin/proverif`、版本 2.05；下面的预期表不是实测结果。

完整 baseline 日志现已 [归档并核对模型摘要](evidence/ubuntu2204-run02/README.md)。工具建议对输入使用 `[precise]`，因此新增 `--variant precise` 对照；只有输入注解不同，所有安全查询与攻击对照不变。该新版本仍待实际运行，详见阶段性说明中的命令。

## 在 Ubuntu 上运行

不需要重装 ProVerif，不需要安装 Python 包，也不要改变已有密码库环境。

```bash
cd ~/DQ-IA
git status
git fetch origin
git switch feat/proverif-validation
command -v proverif
python3 -m experiments.proverif.run --output experiments/proverif/results_ubuntu
```

如 Git 因本地修改拒绝切换，应先保存自己的工作，不要强制重置。
若终端找不到已安装的工具，可指定路径：

```bash
python3 -m experiments.proverif.run \
  --proverif /home/liuyishan/.opam/default/bin/proverif \
  --output experiments/proverif/results_ubuntu
```

依次运行 5 个模型，每个默认超时 180 s。超时不表示性质成立或不成立；应先检查日志，必要时在新目录增加 `--timeout 600`。
运行器不覆盖非空目录，需要重跑时换用 `--output experiments/proverif/results_ubuntu_02`。
运行结束退出码为 0，且 `status` 为 `matched_expectations`，才表示所有模型的已完成查询与预期一致。
出现语法错误、未知性质、缺失结果、无法证明、非零退出码或超时，均返回 `needs_investigation` 和非零退出码，不能当作验证通过。

## 将这些记录反馈给协作者

- `results_ubuntu/validation.json`：实际工具版本、模型 SHA-256、逐项观察值、与预期的比较和进程退出状态。
- `results_ubuntu/tool_version.txt`：实际版本信息。
- `results_ubuntu/*.log`：5 个模型的完整 stdout/stderr，包含结果行和工具输出的攻击推导/轨迹。

可一次打包后作为聊天附件上传：

```bash
tar -czf proverif_results_ubuntu.tar.gz -C experiments/proverif results_ubuntu
```

`validation.json` 是首要核对文件，但应保留全部 `.log` 以区分真实攻击、近似导致的无法证明和语法/执行失败。
协作者未直接连接你的虚拟机，后续将依据你提供的记录核对并归档实际结论。

## 为什么不是所有查询都应该为 TRUE

`query event(accepted_any()).` 检查接受事件是否不可达。工具报告 `not event(accepted_any) is false`，意味着存在接受执行，是本实验期望的非空验证。
`accepted_both` 同理检查两条不同序列号均可接受；不是“所有网络调度都保证交付”，攻击者仍能阻断通信。

去掉重放状态或泄露密钥的对照，预期应发现对应性质不成立。全部 TRUE 反而可能意味着对照或事件模型有问题。

以下为**待实际运行检验的预期**，不是已经获得的结果：

|模型|命令秘密性|非单射来源认证|单射认证|正常接受可达|
|---|---|---|---|---|
|bounded_secure|TRUE|TRUE|TRUE|是；两条不同指令均可接受|
|bounded_no_replay|TRUE|TRUE|FALSE：重复接受|是|
|bounded_root_leak|TRUE|FALSE：根密钥持有者可伪造|FALSE|是|
|bounded_kem_key_leak|FALSE：解密诚实报文|TRUE|TRUE|是|
|unbounded_core|TRUE|TRUE|FALSE：未建模重放状态|是|

这里的单射认证定义为 `inj-event(accepted(ctx,e,seq,m)) ==> inj-event(sent(ctx,e,seq,m))`。
一份诚实发送事件不能对应多次接受；发送事件在输出报文之前发生。非单射认证不禁止对同一诚实发送反复接受。
根密钥泄露时模型公开 `root`，KEM 私钥泄露时公开 `sk`；双方公钥始终公开，不把公钥保密当作安全条件。
每个泄露对照都从开始即泄露，不声称获得前向安全或时序化妥协恢复结论。

## 模型如何对应协议

- 预置信任：每次模型运行创建私有 KEM 私钥和独立认证根密钥；固定 ctx、epoch，不允许报文更新本地配置。
- KEM：公开 `pk`、`kemct`、`kemss` 构造；持有公钥的攻击者可自行选择 coins 并封装，不将 KEM 误建模为发送方认证。
- 解封装：仅对应私钥可从合法 KEM 密文得到共享秘密。畸形 KEM 的隐式拒绝抽象为解密链不成功；不模拟失败时间/响应差异。
- HKDF：显式 Extract 再 Expand，并分别使用 sessionInfo 与 macInfo 构造实现域分离，前者包含 ctx、pk、ct、epoch、seq。
- AEAD：nonce 绑定 epoch/seq，AD 绑定 ctx、epoch、seq、r、ct；只有 key、nonce、AD 都一致才有解密等式。
- 外层 MAC：独立根密钥派生的逐条 MAC 密钥认证 ctx、epoch、seq、r、ct、AEAD 密文；接收先检查 MAC，再解封装和 AEAD。
- `sent`/`accepted`：事件都绑定 ctx、epoch、seq、m；成功后记录接受事件，明文不在公开信道输出。

Encode 的无歧义性以不同元组/构造函数表示；没有建模具体 CBOR、40 B 自定义头或解析器。完整字段/版本/长度检查仍由真实原型测试补充。

## 无界与有限状态的边界

`unbounded_core.pv` 支持无界诚实发送和接收实例，以新生成且最终公开的符号名代表不复用的序列号；不模拟 uint64 数值、计数器数据库或滑动窗口。
它故意不包含防重放状态：可以验证核心秘密性和非单射认证，不能借此声称完整协议满足单射认证。

`bounded_*.pv` 只有一个固定上下文/时期、两个不相同且公开的序列标识、每个一条诚实发送，以及最多三次串行接收尝试。
两个本地已接受标志在成功接受后更新，失败不推进；攻击者仍控制报文投递、修改、插入和重复发送。
这允许比较“启用已接受检查”与“移除检查”的单射性质，但只针对这个有限实例，**不是对任意会话数、64 位序列空间、64 位滑动窗口、窗口淘汰或持久化实现的完整证明**。
模型不声称有限实验可以归纳为无界状态机。真实窗口的 3000 步集合对照和边界用例属于另一个实验层次，也不是该归纳证明。

业务授权/期限检查视为诚实应用允许接受，成功状态提交视为原子理想动作；不模拟执行器、数据库故障或掉电。
密码原语按经典 Dolev–Yao 理想模型抽象，不测量截断 MAC 的猜测概率，不证明标准 ML-KEM 的计算安全性/抗量子安全性，也不涵盖侧信道、资源耗尽和根密钥泄露后的恢复。

## 可维护性与核对器测试

`.pv` 模型由 `generate.py` 生成，分别位于 baseline 的 `models/` 和精确输入对照的 `models_precise/`。默认运行 baseline；`--variant precise` 显式选择后者。重新生成两组模型不会执行 ProVerif：

```bash
python3 -m experiments.proverif.generate
python3 -m unittest discover -s tests/proverif -v
```

核对器的 9 项单元测试只验证 TRUE/FALSE/未知/缺失及 ProVerif 2.05 补充说明行等输出的处理，**这些单元测试本身不代表 ProVerif 已执行或任何安全性质成立**。
不要把 `manifest.json` 的 `expected` 列当作实测结果；真实结论只来自 ProVerif 输出的 RESULT 行，且应结合模型范围和攻击轨迹解释。
