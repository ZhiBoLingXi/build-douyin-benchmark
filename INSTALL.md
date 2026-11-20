# 安装到当前 Agent

仓库地址为 `https://github.com/ZhiBoLingXi/build-douyin-benchmark`。技能名为 `build-douyin-benchmark`，安装单位为完整仓库根目录。已有同名目录时，先确认它的来源和本地改动。

## 1. 安装技能文件

**Codex** 可使用自带的 skill-installer。仓库参数是 `ZhiBoLingXi/build-douyin-benchmark`，路径是 `.`，安装名称是 `build-douyin-benchmark`。也可以直接用 Git：

```sh
skills_dir="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$skills_dir"
git clone https://github.com/ZhiBoLingXi/build-douyin-benchmark.git "$skills_dir/build-douyin-benchmark"
```

**Claude Code** 的用户级目录为 `~/.claude/skills`。[Claude Code 技能文档](https://code.claude.com/docs/en/skills)

```sh
skills_dir="$HOME/.claude/skills"
mkdir -p "$skills_dir"
git clone https://github.com/ZhiBoLingXi/build-douyin-benchmark.git "$skills_dir/build-douyin-benchmark"
```

其他支持目录式 `SKILL.md` 的 Agent 可将同一仓库安装到宿主的用户技能目录。以下命令在 macOS 或 Linux 的 POSIX shell 中运行，`skills_dir` 取上一步的目录。

## 2. 准备采集与分镜环境

需要 Python 3.10+、FFmpeg（含 ffprobe），以及 Chrome 或 Playwright Chromium。先确保 `ffmpeg` 和 `ffprobe` 在 PATH 中。macOS 可用 `brew install ffmpeg`，Linux 可使用系统包管理器安装 `ffmpeg`。

```sh
HERE="$skills_dir/build-douyin-benchmark"
python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/python" -m pip install -r "$HERE/requirements.txt"
```

已安装 Chrome 的环境可直接使用。需要额外安装 Chromium 时运行：

```sh
"$HERE/.venv/bin/python" -m playwright install chromium
```

Linux 上若 Chromium 提示缺少系统组件，可按浏览器安装文档准备依赖。[Playwright Python 文档](https://playwright.dev/python/docs/library)

## 3. 配置本地转写

抽帧、解析作品和安装技能可以先做。要运行包含转写的整套流程，需要本地 Whisper 模型及匹配的 Python 引擎：

- CPU 可安装 `faster-whisper`，使用本地 CTranslate2 模型目录。
- Apple Silicon 可安装 `mlx-whisper`，使用本地 MLX Whisper 模型目录。已有兼容缓存时脚本会尝试自动识别。

例如在 CPU 路径中，以下命令可准备一个支持中文的模型。模型从 Hugging Face 下载一次，转写在本地执行。[faster-whisper 项目说明](https://github.com/SYSTRAN/faster-whisper)

```sh
"$HERE/.venv/bin/python" -m pip install faster-whisper huggingface_hub
MODEL=$("$HERE/.venv/bin/python" -c 'from huggingface_hub import snapshot_download; print(snapshot_download("Systran/faster-whisper-small"))')
```

已有其他模型时可以把 `MODEL` 设为其本地目录。处理已采集的工作目录时运行 `sh "$HERE/scripts/run.sh" media --out "$OUT" --model "$MODEL" --asr-python "$HERE/.venv/bin/python"`。声音模型、浏览器和系统 FFmpeg 按运行平台配置。

## 4. 验证与调用

```sh
test -f "$HERE/SKILL.md" && test -f "$HERE/references/review.md"
ffmpeg -version
ffprobe -version
sh "$HERE/scripts/run.sh" collect --help
sh "$HERE/scripts/run.sh" media --help
sh "$HERE/scripts/run.sh" package --help
```

三个入口都应输出用法并以状态 0 退出。让宿主重新发现技能后，在新一轮对话中发送“用 build-douyin-benchmark 拆解这个账号”并附分享链接，即可开始采集。模型加载及抖音访问在实际处理时验证。子 Skill 的输出位置使用当前宿主的技能目录。
