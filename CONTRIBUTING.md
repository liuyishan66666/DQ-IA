# 开发与实验约定

## 分支与版本

- `main`：已通过本地测试及原始记录审计的完整实验基线。
- `experiments/chapter6`：第六章实验后续工作的起点；初始版本与 `main` 相同。
- `v0.1.0`：首次完整实验快照的 Git 标签。
- 后续修改请从 `main` 创建 `feat/<主题>`、`fix/<主题>` 或 `experiments/<主题>` 分支，通过 Pull Request 合并。
- 提交信息采用 Conventional Commits，例如 `fix(simulation): correct deadline boundary`。

## 修改前后检查

```bash
python -m unittest discover -s tests -v
python -m experiments.chapter6.audit experiments/chapter6/results
```

GitHub Actions 配置会在 Linux、Windows、macOS 上运行模型测试，并单独审计保存的原始记录。
只有实际执行成功的检查才能作为验证证据；工作流文件的存在不代表远端 CI 已通过。

## 实验数据管理

`experiments/chapter6/results/` 是本次实际运行的固定结果，纳入版本管理。
请勿手工修改其指标、事件记录、图表或校验摘要以改变结论。
新实验写入独立目录（例如 `results_local_01`），确认无误后另行决定是否发布为新版本。
更改参数、调度规则、种子或统计方法时，必须重新执行相关实验、测试及审计，并记录与原版本的区别。

原始记录采用 `.csv.gz`，Python 和常用解压软件均可读取，无需 Git LFS。
不要上传虚拟环境、缓存、API 密钥、账号信息或其他无关私人文件。
论文原 PDF 不包含在本仓库；`config.json` 保存了用于本次实验的文件名和 SHA-256。

本仓库未指定开源许可证；发布实验材料不等于授予某一开源许可证。
