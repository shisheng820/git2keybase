import os
import sys
import subprocess
import requests
import urllib.parse
from datetime import datetime

# 获取环境变量
USERNAME = os.environ.get('KEYBASE_USERNAME')
GH_TOKEN = os.environ.get('GITHUB_TOKEN')

def run_cmd(cmd, check=False, silent_error=False):
    """运行终端命令，加入异常处理和静默模式"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
        if result.returncode != 0 and not check and not silent_error:
            err_msg = result.stderr.strip()
            if err_msg:
                print(f"⚠️ 提示/警告: {err_msg}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ 严重错误: 命令 '{cmd}' 执行失败\n{e.stderr}")
        raise

def backup_repo(repo_url):
    # ---------------------------------------------------------
    # 1. 智能解析 URL (兼容任意 Git 平台)
    # ---------------------------------------------------------
    parsed = urllib.parse.urlparse(repo_url)
    domain = parsed.netloc
    # 移除开头的斜杠和结尾的 .git，提取纯路径
    path = parsed.path.lstrip('/')
    if path.endswith('.git'):
        path = path[:-4]
        
    # 提取存储库名称（路径的最后一部分）
    repo_name = path.split('/')[-1] if path else 'unknown'
    
    print(f"\n{'='*50}")
    print(f"🚀 开始处理仓库: {repo_name}")
    
    # 生成安全的 Keybase 目录名 (例如 github.com/a/b -> github_com_a_b)
    safe_name = f"{domain.replace('.', '_')}_{path.replace('/', '_')}"
    # print(f"📁 映射为本地/Keybase目录: {safe_name}")

    # 判断是否为 GitHub，以此决定是否注入 Token 以及是否抓取 Release
    is_github = (domain == "github.com")
    
    if is_github and GH_TOKEN:
        # GitHub 仓库 + 有 Token：注入 Token 防限流/支持私有库
        git_url = f"https://x-access-token:{GH_TOKEN}@github.com/{path}.git"
        github_api_path = path
    else:
        # 其他 Git 平台 或 无 Token：直接匿名拉取原生 URL
        git_url = repo_url
        github_api_path = None

    repo_dir = f"{safe_name}.git"

    # ==========================================
    # 2. 代码增量备份 (所有平台通用)
    # ==========================================
    try:
        run_cmd(f"keybase git create {safe_name} || true", silent_error=True)
        
        if os.path.exists(repo_dir):
            print("📦 发现本地缓存，执行增量 Fetch...")
            os.chdir(repo_dir)
            run_cmd(f"git fetch {git_url} '*:*' --force --tags", check=True)
        else:
            print("📥 无本地缓存，执行全新 Bare Clone...")
            run_cmd(f"git clone --bare {git_url} {repo_dir}", check=True)
            os.chdir(repo_dir)

        # 锚定防删 Tag
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_cmd(f"git tag archive-{timestamp}")
        
        kb_remote = f"keybase://private/{USERNAME}/{safe_name}"
        run_cmd("git remote remove keybase || true", silent_error=True)
        run_cmd(f"git remote add keybase {kb_remote}")
        
        print("☁️ 正在推送到 Keybase...")
        
        # 1. 尝试以镜像模式强制推送，这会强制让 Keybase 与本地（从源拉取）保持完全一致
        # 这通常能解决由于远端和本地 Refs 不匹配导致的 rejected 问题
        push_mirror_result = run_cmd("git push keybase --mirror --force", silent_error=True)
        
        if push_mirror_result.returncode != 0:
            print("⚠️ 镜像推送失败，尝试降级为分步推送...")
            # 2. 如果镜像推送失败，回退到原来的按引用推送，但移除 check=True
            # 这样即使有部分特定的 tag 被拒绝，也不会抛出异常阻断整个流程
            run_cmd("git push keybase --all --force", silent_error=True)
            run_cmd("git push keybase --tags", silent_error=True)
            
            # 只要把刚刚打的防删时间戳 tag 推送成功即可
            check_tag_push = run_cmd(f"git push keybase archive-{timestamp}")
            if check_tag_push.returncode != 0:
                raise Exception(f"关键防删 Tag 推送失败: archive-{timestamp}")
        
        os.chdir("..")
        print("✅ Git 代码备份/同步完成")
        
    except Exception as e:
        print(f"🚨 Git 同步失败，跳过此仓库: {e}")
        if os.path.exists(repo_dir) and os.getcwd().endswith(repo_dir):
            os.chdir("..")
        return # 跳过 release 下载

# ==========================================
    # 3. Release 附件备份 (智能兼容 GitHub & Gitea/Forgejo)
    # ==========================================
    print(f"🔍 尝试探测并检查 {domain} 的 Releases...")

    # 根据域名智能组装 API URL
    if is_github:
        api_url = f"https://api.github.com/repos/{path}/releases?per_page=100"
        headers = {"Authorization": f"token {GH_TOKEN}"} if GH_TOKEN else {}
    else:
        # 尝试使用 Gitea/Forgejo/Gogs 通用的 V1 API
        api_url = f"https://{domain}/api/v1/repos/{path}/releases?limit=100"
        headers = {} # 暂不考虑自建站的 Token，走匿名公开读取

    try:
        # 加入较短的 timeout 防止自建站由于网络问题卡死 Action
        resp = requests.get(api_url, headers=headers, timeout=10)
        
        # 如果返回 404 或其他非 200 状态，说明平台不支持此 API，优雅跳过
        if resp.status_code != 200:
            print(f"ℹ️ 当前平台 {domain} 不支持兼容的 Release API 或无权访问 (HTTP {resp.status_code})，跳过 Release 备份。")
            return

        releases = resp.json()
        
        # 容错：确保返回的是列表格式（兼容 GitHub/Gitea 数据结构）
        if not releases or not isinstance(releases, list):
            print("ℹ️ 该仓库没有 Release，或返回的数据格式无法识别，跳过。")
            return

        # 截取前 3 个最新的 Release
        top_releases = releases[:3]
        keep_tags = [r.get('tag_name', 'unknown') for r in top_releases]
        print(f"📌 目标备份版本 (Top 3): {', '.join(keep_tags)}")

        # 唤醒 KBFS 并创建目录
        run_cmd(f"keybase fs ls /keybase/private/{USERNAME} > /dev/null 2>&1 || true")
        kb_release_base = f"/keybase/private/{USERNAME}/releases"
        kb_release_dir = f"{kb_release_base}/{safe_name}"
        run_cmd(f"keybase fs mkdir {kb_release_base} || true", silent_error=True)
        run_cmd(f"keybase fs mkdir {kb_release_dir} || true", silent_error=True)

        # 自动清理旧版本文件
        print("🧹 开始检查并清理旧版本...")
        ls_result = run_cmd(f"keybase fs ls {kb_release_dir}", silent_error=True)
        if ls_result.returncode == 0:
            existing_files = ls_result.stdout.splitlines()
            for file in existing_files:
                file = file.strip()
                if not file: continue
                if not any(file.startswith(f"{tag}_") for tag in keep_tags):
                    print(f"  🗑️ 删除过期文件: {file}")
                    run_cmd(f"keybase fs rm {kb_release_dir}/{file}")

        # 开始解析和下载 Asset
        for release in top_releases:
            tag_name = release.get('tag_name', 'unknown')
            for asset in release.get('assets', []):
                file_name = f"{tag_name}_{asset.get('name', 'unknown_asset')}"
                kb_file_path = f"{kb_release_dir}/{file_name}"
                
                check = run_cmd(f"keybase fs stat {kb_file_path}", silent_error=True)
                if check.returncode != 0:
                    # Gitea 的 size 可能返回空，加个 get 容错
                    size_mb = asset.get('size', 0) / 1024 / 1024
                    print(f"  ⬇️ 下载大文件: {file_name} ({size_mb:.2f} MB)")
                    
                    # 防止部分自建站的 browser_download_url 缺失或不规范
                    download_url = asset.get('browser_download_url')
                    if not download_url:
                        print(f"  ⚠️ 找不到下载链接，跳过 {file_name}")
                        continue

                    with requests.get(download_url, stream=True, timeout=60) as r:
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

    except requests.exceptions.RequestException as e:
        print(f"🚨 请求 Release API 失败 (可能是网络或 API 不兼容): {e}")
    except Exception as e:
        print(f"🚨 Release 备份发生意外错误: {e}")

if __name__ == "__main__":
    # 从环境变量读取 Gist URL
    gist_url = os.environ.get('REPOS_GIST_URL')
    
    if not gist_url:
        print("❌ 未设置环境变量 REPOS_GIST_URL，无法获取仓库列表！")
        sys.exit(1)
        
    print(f"📄 正在从 Gist 获取仓库列表...")
    try:
        # 如果是私有 Gist，通常 Raw URL 本身包含复杂的 ID 作为鉴权，直接 GET 即可。
        # 但为了兼容性，如果环境变量中有 GITHUB_TOKEN，我们为其加上鉴权请求头。
        headers = {"Authorization": f"token {GH_TOKEN}"} if GH_TOKEN else {}
        resp = requests.get(gist_url, headers=headers, timeout=15)
        resp.raise_for_status() # 检查 HTTP 状态码是否为 200
        
        # 解析文本内容
        repos_content = resp.text
        repos = [line.strip() for line in repos_content.splitlines() if line.strip() and not line.startswith('#')]
        
        if not repos:
            print("⚠️ Gist 内容为空或没有找到有效的仓库 URL！")
            sys.exit(1)
            
        print(f"✅ 成功加载 {len(repos)} 个仓库配置。")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ 从 Gist 获取仓库列表失败: {e}")
        sys.exit(1)
    
    # 遍历列表执行备份
    for r in repos:
        backup_repo(r)
    
    print("\n🎉 所有仓库处理完毕！")