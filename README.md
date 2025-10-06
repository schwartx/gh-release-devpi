# gh-release-devpi

从 GitHub Release 下载构建产物并上传到 DevPI 服务器的命令行工具。

## 安装

```bash
pip install gh-release-devpi
```

## 使用

### 环境变量

创建 `.env` 文件：

```bash
GITHUB_PAT=your_github_personal_access_token
GITHUB_REPO=owner/repo
DEVPI_PASSWORD=your_devpi_password
```

### 命令

下载最新 release 的所有 artifacts 并上传到 DevPI：

```bash
gh-release-devpi download
```

仅下载不上传：

```bash
gh-release-devpi download --skip-upload
```

指定参数：

```bash
gh-release-devpi download \
  --repo owner/repo \
  --token ghp_xxx \
  --output ./dist \
  --devpi-password xxx
```

### 参数

- `--repo`, `-r`: GitHub 仓库 (格式: `owner/repo`)
- `--token`, `-t`: GitHub Personal Access Token
- `--output`, `-o`: 下载目录 (默认: `artifacts`)
- `--devpi-password`, `-p`: DevPI 密码
- `--skip-upload`: 跳过上传到 DevPI

## 开发

```bash
# 安装依赖
pip install -e .

# 运行
python -m gh_release_devpi.main download
```
