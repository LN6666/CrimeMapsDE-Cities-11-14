# CrimeMapsDE-Cities-11-14

德国城市犯罪地图工程的第三组仓库，城市及编号固定为：

| 编号 | 城市 | slug | 当前状态 |
| --- | --- | --- | --- |
| 11 | Essen（埃森） | `essen` | 警方原生公告采集器；未发布地图 |
| 12 | Dresden（德累斯顿） | `dresden` | 尚未启动 |
| 13 | Hannover（汉诺威） | `hannover` | 尚未启动 |
| 14 | Nuremberg（纽伦堡） | `nuremberg` | 尚未启动 |

柏林仍是第一组 `CrimeMapsBerlin` 的默认入口。本仓库目前只有埃森的来源采集和合成测试，没有城市地图、坐标或可发布数据。仓库名称中的 11–14 是城市组编号，不表示覆盖或完成进度。

## 埃森来源与边界

采集器从[Polizei Essen 原生公告档案](https://essen.polizei.nrw/presse/pressemitteilungen)读取分页索引和原文，每次运行先核验 [robots.txt](https://essen.polizei.nrw/robots.txt)，按至少一秒间隔请求，并对暂时性网络错误作有界重试。原生文章的 Drupal 节点 ID、规范 URL、发布时间、正文、SHA-256、修订号和待审状态保存在本地 SQLite。抓取过程不推断地点，也不制作公共地图。

警方署名公告可能涉及 Mülheim an der Ruhr、Oberhausen 和跨市高速路。`city_scope` 只提供保守的市域复核线索；发布机关、邮编或新闻室标签均不能证明案发地在 Essen。多地点、混合辖区、高速与不明确地点进入 `needs_review`。每篇公告仍须逐条对照官方原文接受 Codex 审查，再交项目所有者检查、质问和批准；缺失、过期或不确定的审查阻止发布。

2026-09-28 的有限核对中，原生档案的 2026 年筛选显示 401 条，[Polizei Essen 署名新闻室](https://www.presseportal.de/blaulicht/nr/11562)显示 418 条。两处数量不同，原因尚未核实；这里不宣称完整年度覆盖。警方公告本身也不是全量犯罪记录。

## 本地运行

需要 Python 3.12 和 `uv`。

```sh
uv sync --locked
uv run ruff check .
uv run pytest -q
# 有界的原生来源试跑：最多 1 页索引、1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.essen --year 2026 --max-pages 1 --limit 1
```

默认数据库在 `.runtime/safety/cities/essen/police.sqlite`。`--full` 会在多次运行间记录年档案页码；`--max-pages` 和 `--limit` 只限制**一次网络采集运行**的请求量，并非三天审查篇数或发布时间表。再次运行可从本地断点继续。来源失效时保持上次已保存的原文和修订，不生成替代数据。

`.runtime/`、原始公告、SQLite、下载缓存、生成城市数据、个人凭据均不进入 Git。CI 只运行合成测试，不向警方网站发请求。任何获准的公共数据版本应先完成来源审查、质量检查和所有者批准，并遵循第一组仓库的发布流程。

代码沿用 Apache-2.0 许可，见 [LICENSE](LICENSE)。
