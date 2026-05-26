# Commit 快速检查 — 由 hermes-repo-watcher 自动触发

## 任务
检查仓库 {{REPO_NAME}} 的最新 push 到 {{BRANCH}} 分支

## 检查项
1. commit 信息是否清晰（语义化 commit）
2. 是否有遗留的调试代码（print/console.log/breakpoint）
3. 是否有明显语法错误或类型问题
4. 变更文件是否符合项目规范

## 输出
只需报告需要关注的项，一切正常则输出「✅ 一切正常」
