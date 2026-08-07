# Open Dictionary for Dictionary.app

把 [ahpxex/open-dictionary](https://github.com/ahpxex/open-dictionary) 的
84,212 条英汉学习词条装进 macOS 自带的「词典.app」，Spotlight、三指查词、
右键「查询」全都能用。

## 安装

```bash
brew tap wesleyel/dict https://github.com/wesleyel/open-dictionary-apple
brew install --cask open-dictionary
```

装完在 **词典.app → 设置** 里勾选 *Open Dictionary* 启用。

不用 Homebrew 就到 [Releases](https://github.com/wesleyel/open-dictionary-apple/releases)
下 zip，解压后把 `Open Dictionary.dictionary` 拖进 `~/Library/Dictionaries/`。

## 自己构建

```bash
make fetch     # 下载上游数据（~97 MB）
make install   # 转换 → 编译 → 装进 ~/Library/Dictionaries
```

先小样试跑：`make dict LIMIT=500`。冒烟测试：`make test`。

## 文档

| | |
|---|---|
| [docs/build.md](docs/build.md) | 构建流程、依赖、参数、排错 |
| [docs/ci.md](docs/ci.md) | GitHub Actions 与发版 |
| [docs/format.md](docs/format.md) | 数据契约到 Apple 词典格式的映射 |

## 许可

转换工具 MIT（[LICENSE](LICENSE)）。**词典数据 CC BY-SA 4.0**，源自 Wiktionary，
再分发须保留署名并以相同许可发布 —— 见 [LICENSE-DATA.md](LICENSE-DATA.md)。
