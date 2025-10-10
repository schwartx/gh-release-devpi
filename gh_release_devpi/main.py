import glob
import hashlib
import os
import re
import shutil
import time
from typing import Annotated
from dotenv import load_dotenv
from github import Auth, Github, UnknownObjectException
from github.GitReleaseAsset import GitReleaseAsset
from requests.auth import HTTPBasicAuth
from tqdm import tqdm
import requests
import typer
from rich.console import Console

_ = load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))

app = typer.Typer(help="GitHub Release Artifact Downloader and DevPI Uploader")
console = Console()


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def format_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读格式"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f}PB"


def clear_artifacts_dir(dest_dir: str = "artifacts"):
    """清空 artifacts 目录（如果存在）"""
    if os.path.exists(dest_dir):
        console.print(f"[yellow]清空目录:[/yellow] {dest_dir}")
        shutil.rmtree(dest_dir)
    ensure_dir(dest_dir)


def extract_package_metadata(filename: str) -> dict[str, str]:
    """从文件名提取包名和版本号"""
    # 匹配模式：name-version-...
    # 例: ffactory_rs-0.1.2-cp313-abi3-manylinux...whl
    # 或: package_name-1.0.0.tar.gz

    basename = os.path.basename(filename)

    # 尝试匹配 wheel 格式: {name}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    wheel_pattern = r'^([a-zA-Z0-9_]+)-([0-9][a-zA-Z0-9._]*?)-(.*?)\.whl$'
    match = re.match(wheel_pattern, basename)
    if match:
        return {'name': match.group(1), 'version': match.group(2)}

    # 尝试匹配 sdist 格式: {name}-{version}.tar.gz 或 {name}-{version}.zip
    sdist_pattern = r'^([a-zA-Z0-9_]+)-([0-9][a-zA-Z0-9._]*?)\.(tar\.gz|zip|tar\.bz2|egg)$'
    match = re.match(sdist_pattern, basename)
    if match:
        return {'name': match.group(1), 'version': match.group(2)}

    # 无法解析，返回空
    console.print(f"[yellow]警告: 无法从文件名解析包信息: {basename}[/yellow]")
    return {'name': 'unknown', 'version': '0.0.0'}


def compute_file_hash(file_path: str) -> tuple[str, str]:
    """计算文件的 MD5 和 SHA256"""
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()

    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            md5_hash.update(chunk)
            sha256_hash.update(chunk)

    return md5_hash.hexdigest(), sha256_hash.hexdigest()


def upload_to_devpi(
    devpi_password: str = "",
    devpi_user: str = "root",
    devpi_server: str | None = None,
    devpi_index: str = "dev",
    artifacts_dir: str = "artifacts",
    use_proxy: bool = False
):
    """使用 requests 直接上传文件到 devpi"""
    if not devpi_server:
        raise RuntimeError("必须指定 devpi_server 参数")

    # 构建上传 URL
    upload_url = f"{devpi_server.rstrip('/')}/{devpi_user}/{devpi_index}/"
    console.print(f"[cyan]上传到: {upload_url}[/cyan]")

    # HTTP Basic Auth
    auth = HTTPBasicAuth(devpi_user, devpi_password)

    # 代理设置：默认禁用代理，避免使用系统环境变量中的代理
    proxies = None if use_proxy else {'http': None, 'https': None}
    if not use_proxy:
        console.print("[cyan]已禁用代理[/cyan]")

    # 查找所有包文件
    package_files = []
    for ext in ['*.whl', '*.tar.gz', '*.zip', '*.egg']:
        package_files.extend(glob.glob(os.path.join(artifacts_dir, ext)))

    if not package_files:
        console.print("[yellow]未找到任何包文件（.whl, .tar.gz, .zip, .egg）[/yellow]")
        return

    console.print(f"[cyan]找到 {len(package_files)} 个包文件[/cyan]")

    # 上传每个文件
    success_count = 0
    for file_path in package_files:
        filename = os.path.basename(file_path)
        console.print(f"[cyan]上传: {filename}...[/cyan]")

        try:
            # 提取包元数据
            metadata = extract_package_metadata(filename)
            md5_digest, sha256_digest = compute_file_hash(file_path)

            with open(file_path, 'rb') as f:
                files = {'content': (filename, f, 'application/octet-stream')}

                # 包含完整的 metadata，参考 twine 的实现
                data = {
                    ':action': 'file_upload',
                    'protocol_version': '1',
                    'name': metadata['name'],
                    'version': metadata['version'],
                    'md5_digest': md5_digest,
                    'sha256_digest': sha256_digest,
                    'filetype': 'bdist_wheel' if filename.endswith('.whl') else 'sdist',
                }

                response = requests.post(
                    upload_url,
                    files=files,
                    data=data,
                    auth=auth,
                    proxies=proxies,
                    timeout=60
                )

                response.raise_for_status()
                console.print(f"[green]  ✓ {filename} 上传成功[/green]")
                success_count += 1

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP {e.response.status_code}"
            if e.response.text:
                error_msg += f": {e.response.text[:200]}"
            console.print(f"[red]  ✗ {filename} 上传失败: {error_msg}[/red]")
            raise RuntimeError(f"上传 {filename} 失败: {error_msg}")
        except Exception as e:
            console.print(f"[red]  ✗ {filename} 上传失败: {e}[/red]")
            raise RuntimeError(f"上传 {filename} 失败: {e}")

    console.print(f"[green]✅ 上传成功！({success_count}/{len(package_files)} 个文件)[/green]")


def _requests_get_stream(
    url: str,
    headers: dict[str, str],
    dest_path: str,
    max_retries: int = 2,
    timeout: int = 30
) -> Exception | None:
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with requests.get(
                url, headers=headers, stream=True, timeout=timeout, allow_redirects=True
            ) as r:
                r.raise_for_status()

                # 尝试获取文件总大小
                total_size = (
                    int(r.headers.get("content-length", 0)) or None
                )  # None 表示未知大小

                with open(dest_path, "wb") as f:
                    # 初始化 tqdm 进度条
                    with tqdm(
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        desc=dest_path.split("/")[-1] or "Downloading",
                        leave=True,
                    ) as pbar:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                _ = f.write(chunk)
                                _ = pbar.update(len(chunk))  # 更新进度条

            return None  # success

        except Exception as exc:
            last_exc = exc
            # small backoff
            time.sleep(0.5 * attempt)

    return last_exc


def download_asset(asset: GitReleaseAsset, token: str, dest_dir: str = "artifacts") -> str:
    """
    更稳健的 release asset 下载：
    1) 优先使用 asset.url (API endpoint) + Accept: application/octet-stream (官方方式)
    返回保存的文件路径或抛出异常
    """
    ensure_dir(dest_dir)
    filename = os.path.join(dest_dir, asset.name)

    # 使用 API 下载端点 (recommended)
    api_url: str = (
        asset.url
    )  # e.g. https://api.github.com/repos/owner/repo/releases/assets/12345
    headers_api: dict[str, str] = {
        "Authorization": f"token {token}",
        "Accept": "application/octet-stream",
    }

    err = _requests_get_stream(api_url, headers_api, filename)
    if err is None:
        return filename

    # 失败，抛出带上下文的异常
    raise RuntimeError(f"Failed to download asset {asset.name}.")


@app.command()
def download(
    repo_name: Annotated[
        str | None,
        typer.Option(
            "--repo",
            "-r",
            envvar="GITHUB_REPO",
            help="GitHub 仓库名称 (格式: owner/repo, 从环境变量 GITHUB_REPO 读取)"
        )
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            envvar="GITHUB_PAT",
            help="GitHub Personal Access Token (默认从环境变量 GITHUB_PAT 读取)"
        )
    ] = None,
    artifacts_dir: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="下载文件保存目录"
        )
    ] = "artifacts",
    devpi_password: Annotated[
        str | None,
        typer.Option(
            "--devpi-password",
            "-p",
            envvar="DEVPI_PASSWORD",
            help="DevPI 密码 (如果需要上传到 DevPI, 从环境变量 DEVPI_PASSWORD 读取)"
        )
    ] = None,
    devpi_user: Annotated[
        str,
        typer.Option(
            "--devpi-user",
            "-u",
            envvar="DEVPI_USER",
            help="DevPI 用户名 (从环境变量 DEVPI_USER 读取, 默认: root)"
        )
    ] = "root",
    devpi_server: Annotated[
        str | None,
        typer.Option(
            "--devpi-server",
            "-s",
            envvar="DEVPI_SERVER",
            help="DevPI 服务器地址 (从环境变量 DEVPI_SERVER 读取)"
        )
    ] = None,
    devpi_index: Annotated[
        str,
        typer.Option(
            "--devpi-index",
            "-i",
            envvar="DEVPI_INDEX",
            help="DevPI 索引名称 (从环境变量 DEVPI_INDEX 读取, 默认: dev)"
        )
    ] = "dev",
    devpi_use_proxy: Annotated[
        bool,
        typer.Option(
            "--devpi-use-proxy",
            envvar="DEVPI_USE_PROXY",
            help="上传到 DevPI 时使用系统代理 (默认不使用代理)"
        )
    ] = False,
    skip_upload: Annotated[
        bool,
        typer.Option(
            "--skip-upload",
            help="跳过上传到 DevPI"
        )
    ] = False,
) -> None:
    """
    从 GitHub Release 下载 artifacts 并可选上传到 DevPI
    """
    if not token:
        console.print("[red]错误: GITHUB_PAT 未设置，请通过 --token 参数或环境变量提供[/red]")
        raise typer.Exit(code=1)

    if not repo_name:
        console.print("[red]错误: GITHUB_REPO 未设置，请通过 --repo 参数或环境变量提供[/red]")
        raise typer.Exit(code=1)

    try:
        auth = Auth.Token(token)
        g = Github(auth=auth)
        repo = g.get_repo(repo_name)

        try:
            latest_release = repo.get_latest_release()
        except UnknownObjectException:
            console.print(f"[red]仓库 {repo_name} 没有 Release。[/red]")
            raise typer.Exit(code=1)

        console.print("[bold green]最新 release:[/bold green]")
        console.print(f"  [cyan]name:[/cyan] {latest_release.name or latest_release.tag_name}")
        console.print(f"  [cyan]tag_name:[/cyan] {latest_release.tag_name}")
        console.print(f"  [cyan]published_at:[/cyan] {latest_release.published_at}")
        console.print(f"  [cyan]url:[/cyan] {latest_release.html_url}")

        assets = list(latest_release.get_assets())
        if not assets:
            console.print("[yellow]该 release 没有 assets（artifact）。[/yellow]")
            raise typer.Exit(code=0)

        console.print(f"\n[bold]找到 {len(assets)} 个 asset:[/bold]")
        for i, a in enumerate(assets, start=1):
            console.print(f" {i}. [green]{a.name}[/green]  size={format_size(a.size)}  created_at={a.created_at}")

        # 清空 artifacts 目录
        clear_artifacts_dir(artifacts_dir)

        console.print(f"\n[bold cyan]开始下载 assets 到 ./{artifacts_dir}/ ...[/bold cyan]")
        failed_downloads: list[str] = []
        for a in assets:
            try:
                saved = download_asset(a, token, dest_dir=artifacts_dir)
                console.print(f"  [green]✓ 下载完成:[/green] {saved}")
            except Exception as exc:
                console.print(f"  [red]✗ 下载失败:[/red] {a.name} — {repr(exc)}")
                failed_downloads.append(a.name)

        if failed_downloads:
            console.print(f"\n[yellow]警告: {len(failed_downloads)} 个文件下载失败[/yellow]")

        # 上传到 devpi
        if not skip_upload:
            try:
                console.print("")
                upload_to_devpi(
                    devpi_password=devpi_password or "",
                    devpi_user=devpi_user,
                    devpi_server=devpi_server,
                    devpi_index=devpi_index,
                    artifacts_dir=artifacts_dir,
                    use_proxy=devpi_use_proxy
                )
            except Exception as e:
                console.print(f"[red]❌ 上传失败: {e}[/red]")
                raise typer.Exit(code=1)
        else:
            console.print("\n[yellow]已跳过上传到 DevPI (--skip-upload)[/yellow]")

        console.print("\n[bold green]✅ 任务完成！[/bold green]")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]发生错误: {e}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

