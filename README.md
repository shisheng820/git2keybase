# Git & Release to Keybase Backup (Ultra)

高健壮性的自动化备份方案，专门应对大仓库、私有库、重名库以及原作者删库跑路的风险。

## 架构优化亮点
- **真·增量同步**: 结合 GitHub Actions 原生缓存 (`actions/cache`)，每次运行只拉取 Git 增量数据，杜绝全量 Clone 导致的超时和带宽高耗。
- **大文件流式处理**: Release 附件采用 chunk 分块下载，支持上 GB 的单个附件稳定备份。
- **强制锚定防删**: 自动植入时间戳 Tag 推送至 Keybase，无视上游的 `force-push`。
- **独立容灾处理**: 单个仓库的失败（如 Token 失效、API 异常）不会引发整个任务链崩溃。

## 配置指南
1. 在仓库的 **Settings -> Secrets and variables -> Actions** 中添加：
   - `KEYBASE_USERNAME`: Keybase 用户名
   - `KEYBASE_PAPERKEY`: Keybase 纸质密钥
   *(可选)* 若需备份你账号下**未授权给当前 Action** 的私有库，需新增 `PAT_TOKEN` 并替换 workflow 中的 `GITHUB_TOKEN`。
2. 编辑 `repos.txt`，按行写入目标仓库（格式：`author/repo`）。
3. 推送代码，享受免维护的云端加密备份。