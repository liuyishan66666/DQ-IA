# 用户 Ubuntu：baseline 模型第二次运行记录

来源为用户上传的 `proverif_results_ubuntu_02.tar.gz`，不是协作者直接访问虚拟机取得。
实际环境为 ProVerif 2.05、Python 3.10.12、x86_64、glibc 2.35。

- `raw_results.tar.gz`：上传包的原样副本，含全部 5 份日志、原 validation.json、tool_version.txt。
- `validation_original.json`：原始 JSON 的逐字节副本，保留旧解析器报错，未改写历史记录。
- `validation_reparsed.json`：修正解析器重新读取同一日志后的结果，注明没有重新执行工具；与原运行的返回码、超时及模型摘要一起核对。
- `models/`：与原 JSON 的 5 个 SHA-256 全部匹配的模型快照及当时的查询预期。
- `diagnostic_excerpt.txt`：三个未解决单射查询的轨迹重建失败、精确输入建议及结果行，附原日志行号。
- `provenance.json`：原始附件 SHA-256、处理说明和核对范围。

重新解析后，`bounded_root_leak` 和 `unbounded_core` 的已完成结果与预期一致；其余三个模型的单射查询仍未解决，保留 `needs_investigation`。
这是完整日志归档及诊断证据，不能称为所有形式化验证通过。

后续 `precise` 版本的结果应存入新的目录，不覆写本次 baseline 记录。
