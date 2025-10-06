import os
import shutil
import subprocess
import time
from typing import Annotated
from dotenv import load_dotenv
from github import Auth, Github, UnknownObjectException
from github.GitReleaseAsset import GitReleaseAsset
from tqdm import tqdm
import requests
import typer
from rich.console import Console

_ = load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))

app = typer.Typer(help="GitHub Release Artifact Downloader and DevPI Uploader")
console = Console()


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def clear_artifacts_dir(dest_dir: str = "artifacts"):
    """清空 artifacts 目录（如果存在）"""
    if os.path.exists(dest_dir):
        console.print(f"[yellow]清空目录:[/yellow] {dest_dir}")
        shutil.rmtree(dest_dir)
    ensure_dir(dest_dir)


def upload_to_devpi(devpi_password: str = "", artifacts_dir: str = "artifacts"):
    """使用 subprocess 调用 devpi 命令上传文件"""
    console.print("[cyan]登录 devpi...[/cyan]")
    login_cmd = ["devpi", "login", "root", "--password", devpi_password]
    result = subprocess.run(login_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"devpi login 失败: {result.stderr.strip()}")

    console.print("[cyan]上传 artifacts...[/cyan]")
    upload_cmd = ["devpi", "upload", "--from-dir", artifacts_dir]
    result = subprocess.run(upload_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"devpi upload 失败: {result.stderr.strip()}")

    console.print("[green]✅ 上传成功！[/green]")
    console.print(result.stdout)


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
            console.print(f" {i}. [green]{a.name}[/green]  size={a.size} bytes  created_at={a.created_at}")

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
                upload_to_devpi(devpi_password or "", artifacts_dir)
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

