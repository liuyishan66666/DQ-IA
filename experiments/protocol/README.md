# Ubuntu 协议原型与状态机实验

本实验与第六章网络仿真独立：真实运行 ML-KEM-768、ChaCha20-Poly1305、HKDF-SHA-256 和 128 位截断 HMAC-SHA-256，按论文第 5 节的 Send/Recv 顺序进行测试。

目标环境：Ubuntu 22.04 LTS、x86_64、Python 3.10。无需重装系统或升级到 Python 3.12；无需 QEMU、GPU、ProVerif 或 root 权限运行实验。
依赖 `pqcrypto==0.4.0` 提供 ML-KEM 实现，`cryptography==46.0.3` 提供 AEAD；不使用模拟 KEM，也不关闭 TLS/校验检查。

## 在 Ubuntu 虚拟机执行

在仓库目录先检查本地状态：

```bash
cd ~/DQ-IA
git status
git fetch origin
git switch --track origin/feat/protocol-validation
```

若本地已经有 `feat/protocol-validation` 分支，则用 `git switch feat/protocol-validation` 和 `git pull --ff-only`。
如果有未提交修改或 Git 阻止切换，请先保存自己的工作，不要使用 `reset --hard` 或强制切换。

创建与网络仿真分开的虚拟环境：

```bash
python3 -m venv .venv-protocol
source .venv-protocol/bin/activate
python -m pip install --only-binary=:all: -r experiments/protocol/requirements.txt
python -m pip check
python -m experiments.protocol.run --output experiments/protocol/results_ubuntu
```

若 `venv` 提示缺少组件，只需安装：

```bash
sudo apt install python3-venv
```

本实验不用安装 `experiments/chapter6/requirements.txt`；其绘图依赖针对另一环境，不能与本实验的 Python 3.10 要求混为一谈。
`--only-binary=:all:` 安装已有 Linux wheel，避免在虚拟机编译密码库；Ubuntu 22.04 的 glibc 2.35 满足所选 wheel 的要求。
出现下载/证书错误时保留完整报错，不要使用 `--trusted-host` 等绕过验证。

## 成功标准与反馈材料

正常结束应显示 33 个测试通过、`status: passed`，并显示：

```json
{
  "plaintext_bytes": 32,
  "wire_bytes": 1208,
  "custom_header_bytes": 40,
  "roundtrip_matches": true,
  "replay_rejected": true,
  "invalid_mac_rejected": true,
  "invalid_mac_decapsulation_calls": 0,
  "accepted_pending_commands": 1
}
```

将下面两个文件反馈给协作者即可，不需要发送密钥、SQLite 数据库或虚拟环境：

- `experiments/protocol/results_ubuntu/validation.json`：版本、每项测试状态、源码摘要和功能演示结果。
- `experiments/protocol/results_ubuntu/test_run.txt`：完整测试日志。

运行器不覆盖非空结果目录。需要重跑时改用 `--output experiments/protocol/results_ubuntu_02`。
失败时返回非零退出码，JSON 会区分失败、错误、跳过；依赖未安装或无法导入导致运行器无法启动时，直接保留终端报错。
密钥由密码库和系统安全随机源生成；不固定密码随机数以追求字节级相同输出，也不将明文或密钥写入共享实验日志。

## 33 项测试覆盖

- ML-KEM 真正封装/解封装，HKDF 与 RFC 5869 测试向量对照。
- 32 B 指令收发，空明文及 4096 B 上限，超长明文拒绝。
- 固定字段解析、长度、协议版本、上下文、随机量、KEM 密文、AEAD 密文及 MAC 篡改。
- 无效 MAC、错误时期、错误认证根密钥及未认证大序列号均不触发解封装。
- 错误 KEM 私钥、带有效外层 MAC 的畸形 KEM 密文及 AEAD 篡改最终被 AEAD 拒绝。
- 重复拒绝、窗口内乱序、窗口下界与下界外拒绝、位图与独立集合模型的 3000 步对照。
- 业务检查失败/异常、待处理记录写入失败、COMMIT 被拒绝时状态不推进，且不返回接受。
- 计数器先提交再封装，封装失败消耗已预留序号，预留失败不调用 KEM，uint64 上限停止且不回绕。
- 相同配置重新连接时计数器与重放状态保留，跨连接并发重放只接受一次。
- **预期安全边界**：认证根密钥持有者无需探测器私钥即可伪造新指令，该测试成功表示准确复现论文限制，不能解释为抗根密钥泄露认证。

## 线格式与论文公式的对应

原论文没有给出具体 40 B 线格式；本原型作出以下明确选择，以实际验证自定义编码尺寸：

|字段|字节|
|---|---:|
|Magic / 版本 / 套件 / 保留字段|4 / 1 / 1 / 2|
|时期 / 序列号|4 / 8|
|上下文 SHA-256 前 16 B / AEAD 密文长度|16 / 4|
|以上为自定义头小计|40|
|公开随机量 r|16|
|ML-KEM-768 密文|1088|
|AEAD 密文（含 16 B 标签）|明文长度 + 16|
|外层截断 HMAC|16|

因此总长为 `明文长度 + 1176 B`，32 B 指令为 1208 B。
这只验证所选自定义核心报文编码，**不是 BPv7/BPSec 实际封装测量**，不改变第六章 H=40 B 属于假设的定位。
派生和认证中的 Encode 对每个 byte-string 加 uint32 大端长度前缀；整数先编码成固定 uint32/uint64 大端字节。
nonce 为 `uint32be(epoch) || uint64be(seq)`；HKDF extract/expand、域分离标签、AD 和 MAC 覆盖依照论文式 (11)–(20)。
头内版本、套件、保留位和上下文绑定必须与本地固定配置匹配，长度必须与实际密文一致；时期和序列号包含在认证数据中。

## 状态与限制

发送计数器预留、接收位图及待处理指令采用 SQLite 事务。序列号以十进制文本存储，以覆盖 uint64 全范围。
接收采用 `BEGIN IMMEDIATE` 在不同连接间串行化；先 MAC、后 KEM、后 AEAD/业务检查，最后原子写入位图和待处理记录，成功提交后才返回接受。
业务检查为可注入回调；本示例默认接受任意合法明文，具体业务有效期、操作授权、目标参数检查需由应用提供。它不是完整遥控执行器，也不保证物理动作恰好执行一次。

密钥只存在于实验进程内，地面发送对象不持有探测器私钥；临时数据库在测试结束后删除。重新连接测试在同一测试进程使用同一份可信配置，**不代表完成跨进程密钥持久化或掉电恢复验证**。
数据库可能含解密后的待处理指令，应使用可信本地存储，不要上传数据库。生产部署需要独立设计安全配置/密钥存储和受控时期切换；本原型不支持自动 OTAR，不通过普通报文安装新时期。
使用相同密钥的实际收发上下文时，不得通过删除或新建数据库来重置序列号与重放状态。本测试每次新建数据库时也重新生成独立密钥，不复用旧上下文。
Python 无法保证秘密内存擦除；未完成侧信道、故障、任意掉电、磁盘回滚、资源消耗、密码算法合规认证、实际链路、BPSec 互操作或形式化安全证明。
功能测试通过只能支持实现符合这些被测行为，不能替代 ProVerif 或密码安全证明。
