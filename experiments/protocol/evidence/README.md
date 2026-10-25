# 云环境与用户虚拟机验证记录

|目录|实际 Python 版本|协议测试|功能演示|
|---|---|---|---|
|cloud-python310|3.10.22|33 passed，0 failed/error/skipped|32 B → 1208 B，合法收发、重放拒绝、无效 MAC 不调用解封装|
|cloud-python312|3.12.14|33 passed，0 failed/error/skipped|同上|
|ubuntu2204-python31012|3.10.12|33 passed，0 failed/error/skipped|同上；用户提供的 Ubuntu 虚拟机运行记录|

各目录包含实际运行的 `validation.json` 与 `test_run.txt`，记录依赖、源码摘要和逐项结果。
原有第六章 12 项网络模型测试也在 Python 3.10 中通过。

本验证发生在云 Linux 环境（具体内核、glibc 见 JSON），**不是用户的 Ubuntu 22.04.5 虚拟机，也不是完全相同的 Python 3.10.12 补丁版本**。
选定依赖存在 CPython 3.10 / x86_64 Linux wheel；其最低 glibc 要求不高于 Ubuntu 22.04 的 glibc 2.35。
用户随后在 Ubuntu 22.04.5 / Python 3.10.12 虚拟机执行了测试，并提供包含 JSON 与日志的终端粘贴文本。
该记录已归档到 `ubuntu2204-python31012/`：5 个源码 SHA-256 与仓库一致，JSON 和文本的 33 个测试名称与状态一致，全部通过且没有跳过。
其中 `provenance.json` 记录附件摘要和提取方式；JSON 与文本是从上传内容提取并规范化换行的记录，不是协作者直接连接虚拟机取得的原始文件。未改动结果或运行环境字段。
Ubuntu 发行版名称来自用户先前提供的 `/etc/os-release`；本次 JSON 直接记录 Python 3.10.12、x86_64、Linux 6.8.0-138-generic 与 glibc 2.35。

记录只包含测试及软件信息，不包含生成的认证根密钥、KEM 私钥或含明文的 SQLite 数据库。
