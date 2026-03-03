import os
import sys
import subprocess
import requests
from datetime import datetime

# 获取环境变量
USERNAME = os.environ.get('KEYBASE_USERNAME')
GH_TOKEN = os.environ.get('GITHUB_TOKEN')

def run_cmd(cmd, check=False, silent_error=False):
    """运行终端命令，加入异常处理"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
        # 如果不是静默模式，且有错误输出，才打印警告
        if result.returncode != 0 and not check and not silent_error:
            err_msg = result.stderr.strip()
            if err_msg: # 防止打印空的警告
                print(f"⚠️ 提示/警告: {err_msg}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ 严重错误: 命令 '{cmd}' 执行失败\n{e.stderr}")
        raise

def backup_repo(repo_path):
    # 将 author/repo 转换为 author_repo，防止同名冲突
    safe_name = repo_path.replace('/', '_')
    print(f"\n{'='*50}")
    print(f"🚀 开始处理仓库: {repo_path} -> 映射为: {safe_name}")
    
    # 注入 Token 以支持私有仓库 (HTTPS 方式)
    git_url = f"https://x-access-token:{GH_TOKEN}@github.com/{repo_path}.git" if GH_TOKEN else f"https://github.com/{repo_path}.git"
    repo_dir = f"{safe_name}.git"

    # ==========================================
    # 1. 代码增量备份 (结合 Actions 缓存)
    # ==========================================
    try:
        # 确保 Keybase 存在该仓库 (即使存在报错也不中断)
        run_cmd(f"keybase git create {safe_name} || true")
        
        if os.path.exists(repo_dir):
            print("📦 发现本地缓存，执行增量 Fetch...")
            os.chdir(repo_dir)
            run_cmd(f"git fetch {git_url} '*:*' --force --tags", check=True)
        else:
            print("📥 无本地缓存，执行全新 Bare Clone...")
            run_cmd(f"git clone --bare {git_url} {repo_dir}", check=True)
            os.chdir(repo_dir)

        # 打上时间戳防删 Tag
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_cmd(f"git tag archive-{timestamp}")
        
        # 配置 Keybase Remote 并推送
        kb_remote = f"keybase://private/{USERNAME}/{safe_name}"
        run_cmd("git remote remove keybase || true") # 清理可能残留的 remote
        run_cmd(f"git remote add keybase {kb_remote}")
        
        print("☁️ 正在推送到 Keybase...")
        run_cmd("git push keybase --all --force", check=True)
        run_cmd("git push keybase --tags", check=True)
        
        os.chdir("..")
        print("✅ Git 代码备份/同步完成")
        
    except Exception as e:
        print(f"🚨 Git 同步失败，跳过此仓库: {e}")
        if os.path.exists(repo_dir) and os.getcwd().endswith(repo_dir):
            os.chdir("..")
        return # 跳过 release 下载，防止级联失败

# ==========================================
    # 2. Release 附件备份 (只保留最新3个 + 自动清理)
    # ==========================================
    print(f"🔍 检查 {repo_path} 的 Releases...")
    api_url = f"https://api.github.com/repos/{repo_path}/releases?per_page=100"
    headers = {"Authorization": f"token {GH_TOKEN}"} if GH_TOKEN else {}
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        releases = resp.json()
        
        if not releases:
            print("ℹ️ 该仓库没有 Release，跳过。")
            return

        # 核心修改：只截取前 3 个最新的 Release
        top_releases = releases[:3]
        keep_tags = [r.get('tag_name', 'unknown') for r in top_releases]
        print(f"📌 目标备份版本 (Top 3): {', '.join(keep_tags)}")

        # 唤醒和创建目录
        run_cmd(f"keybase fs ls /keybase/private/{USERNAME} > /dev/null 2>&1 || true")
        kb_release_base = f"/keybase/private/{USERNAME}/releases"
        kb_release_dir = f"{kb_release_base}/{safe_name}"
        run_cmd(f"keybase fs mkdir {kb_release_base} || true", silent_error=True)
        run_cmd(f"keybase fs mkdir {kb_release_dir} || true", silent_error=True)

        # ------------------------------
        # 自动清理旧版本文件
        # ------------------------------
        print("🧹 开始检查并清理旧版本...")
        ls_result = run_cmd(f"keybase fs ls {kb_release_dir}", silent_error=True)
        if ls_result.returncode == 0:
            existing_files = ls_result.stdout.splitlines()
            for file in existing_files:
                file = file.strip()
                if not file: continue
                
                # 检查该文件是否属于我们要保留的 top 3 tags
                # 因为我们存的时候文件名格式是 {tag_name}_{asset['name']}
                if not any(file.startswith(f"{tag}_") for tag in keep_tags):
                    print(f"  🗑️ 删除过期文件: {file}")
                    run_cmd(f"keybase fs rm {kb_release_dir}/{file}")
        # ------------------------------

        # 开始备份这 3 个版本
        for release in top_releases:
            tag_name = release.get('tag_name', 'unknown')
            for asset in release.get('assets', []):
                file_name = f"{tag_name}_{asset['name']}"
                kb_file_path = f"{kb_release_dir}/{file_name}"
                
                # 使用 silent_error=True 屏蔽掉 5103 报错
                check = run_cmd(f"keybase fs stat {kb_file_path}", silent_error=True)
                if check.returncode != 0:
                    print(f"  ⬇️ 下载大文件: {file_name} ({asset['size']/1024/1024:.2f} MB)")
                    
                    with requests.get(asset['browser_download_url'], stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(file_name, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                    
                    print(f"  ☁️ 上传到 Keybase FS...")
                    run_cmd(f"keybase fs cp {file_name} {kb_file_path}", check=True)
                    os.remove(file_name)
                    print(f"  ✅ {file_name} 备份成功")
                else:
                    print(f"  ⏭️ {file_name} 已存在，跳过。")
    except Exception as e:
        print(f"🚨 Release 备份失败: {e}")