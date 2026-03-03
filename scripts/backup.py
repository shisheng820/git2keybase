import os
import subprocess
import tempfile
import requests
from datetime import datetime

USERNAME = os.environ.get('KEYBASE_USERNAME')
GH_TOKEN = os.environ.get('GITHUB_TOKEN')

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warn: {result.stderr}")
    return result

def backup_repo(repo_path):
    repo_name = repo_path.split('/')[-1]
    print(f"\nStart backup: {repo_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        run_cmd(f"keybase git create {repo_name}")

        bare_repo_path = os.path.join(tmpdir, f"{repo_name}.git")
        clone_cmd = f"git clone --bare https://github.com/{repo_path}.git {bare_repo_path}"
        run_cmd(clone_cmd)

        timestamp = datetime.now().strftime("%Y%m%d")
        tag_cmd = f"git -C {bare_repo_path} tag archive-{timestamp}"
        run_cmd(tag_cmd)

        remote_cmd = f"git -C {bare_repo_path} remote add keybase keybase://private/{USERNAME}/{repo_name}"
        run_cmd(remote_cmd)

        push_all_cmd = f"git -C {bare_repo_path} push keybase --all --force"
        run_cmd(push_all_cmd)

        push_tags_cmd = f"git -C {bare_repo_path} push keybase --tags"
        run_cmd(push_tags_cmd)

        print("Git backup done")

    api_url = f"https://api.github.com/repos/{repo_path}/releases"
    headers = {"Authorization": f"token {GH_TOKEN}"} if GH_TOKEN else {}
    resp = requests.get(api_url, headers=headers)

    if resp.status_code == 200:
        releases = resp.json()
        kb_release_dir = f"/keybase/private/{USERNAME}/releases/{repo_name}"
        run_cmd(f"keybase fs mkdir -p {kb_release_dir}")

        for release in releases:
            tag_name = release.get('tag_name', 'unknown_version')
            for asset in release.get('assets', []):
                file_name = f"{tag_name}_{asset['name']}"
                kb_file_path = f"{kb_release_dir}/{file_name}"

                check = run_cmd(f"keybase fs ls {kb_file_path}")
                if check.returncode != 0:
                    print(f"  Download: {file_name}")
                    r = requests.get(asset['browser_download_url'])
                    with tempfile.NamedTemporaryFile(delete=False) as f:
                        f.write(r.content)
                        tmp_file = f.name

                    run_cmd(f"keybase fs cp {tmp_file} {kb_file_path}")
                    os.remove(tmp_file)
                    print(f"  Saved: {file_name}")
    else:
        print("No releases or fetch failed.")

if __name__ == "__main__":
    with open("repos.txt", "r") as f:
        repos = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for r in repos:
        backup_repo(r)
