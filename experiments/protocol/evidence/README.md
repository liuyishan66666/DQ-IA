# 云环境验证记录

|目录|实际 Python 版本|协议测试|功能演示|
|---|---|---|---|
|cloud-python310|3.10.22|33 passed，0 failed/error/skipped|32 B → 1208 B，合法收发、重放拒绝、无效 MAC 不调用解封装|
|cloud-python312|3.12.14|33 passed，0 failed/error/skipped|同上|

两个目录各包含实际运行的 `validation.json` 与 `test_run.txt`，记录依赖、源码摘要和逐项结果。
原有第六章 12 项网络模型测试也在 Python 3.10 中通过。

本验证发生在云 Linux 环境（具体内核、glibc 见 JSON），**不是用户的 Ubuntu 22.04.5 虚拟机，也不是完全相同的 Python 3.10.12 补丁版本**。
选定依赖存在 CPython 3.10 / x86_64 Linux wheel；其最低 glibc 要求不高于 Ubuntu 22.04 的 glibc 2.35。
仍需用户按协议 README 在虚拟机中实际执行并保留日志，才能报告虚拟机验证完成。

记录只包含测试及软件信息，不包含生成的认证根密钥、KEM 私钥或含明文的 SQLite 数据库。
