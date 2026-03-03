# Git & Release to Keybase Backup

Automated backup solution to protect GitHub repositories from DMCA takedowns or author abandonment while avoiding unlimited storage growth.

## Features

- **Incremental Sync**: Uses Git's底层机制推送代码，不产生重复包，节省 Keybase 的 250GB 额度
- **Delete Protection**: 自动创建 `archive-YYYYMMDD` 标签，即使原作者 force-push 清除历史，记录仍安全保留
- **Release Backup**: 自动检测新版本 Release 二进制文件，通过 `keybase fs` 直传加密云盘

## Usage

1. Configure GitHub Secrets: `KEYBASE_USERNAME` and `KEYBASE_PAPERKEY`
2. Add repositories to `repos.txt` (format: `owner/repo`, one per line)
3. Commit and push, wait for Action to run or manually trigger from Actions panel

## Required Secrets

| Secret | Description |
|--------|-------------|
| KEYBASE_USERNAME | Your Keybase username |
| KEYBASE_PAPERKEY | Keybase paper key for CI login |
| GITHUB_TOKEN | GitHub token (for API rate limit, optional but recommended) |

## File Structure

```
git-keybase-sync/
├── .github/workflows/sync.yml  # GitHub Actions workflow
├── scripts/backup.py           # Backup script
├── requirements.txt            # Python dependencies
├── repos.txt                   # Repository list
└── README.md                   # This file
```
