# CrimeMapsDE-Cities-11-14

德国城市犯罪地图工程的第三组仓库，城市及编号固定为：

| 编号 | 城市 | slug | 当前状态 |
| --- | --- | --- | --- |
| 11 | Essen（埃森） | `essen` | 警方原生公告采集器；未发布地图 |
| 12 | Dresden（德累斯顿） | `dresden` | 官方来源已核对；仅离线待核验暂存 |
| 13 | Hannover（汉诺威） | `hannover` | 警方链接的新闻室有界采集；未发布地图 |
| 14 | Nuremberg（纽伦堡） | `nuremberg` | 警方署名新闻室有界采集；原生站仅离线暂存，未发布地图 |

柏林仍是第一组 `CrimeMapsBerlin` 的默认入口。本仓库没有城市地图、坐标或可发布数据。仓库名称中的 11–14 是城市组编号，不表示覆盖或完成进度。

## 埃森来源与边界

采集器从[Polizei Essen 原生公告档案](https://essen.polizei.nrw/presse/pressemitteilungen)读取分页索引和原文，每次运行先核验 [robots.txt](https://essen.polizei.nrw/robots.txt)，按至少一秒间隔请求，并对暂时性网络错误作有界重试。原生文章的 Drupal 节点 ID、规范 URL、发布时间、正文、SHA-256、修订号和待审状态保存在本地 SQLite。抓取过程不推断地点，也不制作公共地图。

警方署名公告可能涉及 Mülheim an der Ruhr、Oberhausen 和跨市高速路。`city_scope` 只提供保守的市域复核线索；发布机关、邮编或新闻室标签均不能证明案发地在 Essen。多地点、混合辖区、高速与不明确地点进入 `needs_review`。每篇公告仍须逐条对照官方原文接受 Codex 审查，再交项目所有者检查、质问和批准；缺失、过期或不确定的审查阻止发布。

2026-09-28 的有限核对中，原生档案的 2026 年筛选显示 401 条，[Polizei Essen 署名新闻室](https://www.presseportal.de/blaulicht/nr/11562)显示 418 条。两处数量不同，原因尚未核实；这里不宣称完整年度覆盖。警方公告本身也不是全量犯罪记录。

## 汉诺威来源与边界

[Polizeidirektion Hannover 的新闻办公室](https://www.pd-h.polizei-nds.de/wir_ueber_uns/presse/)明确链接其[Presseportal 新闻室](https://www.presseportal.de/blaulicht/nr/66841)。采集器先核验 Presseportal 的 [robots.txt](https://www.presseportal.de/robots.txt)，再按有界页数读取索引和正文；SQLite 保存新闻室文章 ID、URL、原文哈希、修订与待审状态。年度断点扫描会在续扫时刷新新闻室首页；`--pages` 指续扫页数，实际索引请求最多多一页首页。2026-09-28 的单页试跑发现 30 条、保存 1 篇；这只是断点，不是年度完成量。

新闻室包含 Langenhagen、Lehrte、Burgwedel 等周边地点及高速公路。`hannover_candidate` 只是市域复核线索；含其他市镇或跨市道路的记录保持待核验，不自动进入汉诺威地图。新闻室首页地点标签和 `Hannover (ots)` 发稿地不作为案发地点证据。

## 德累斯顿来源限制

[Polizei Sachsen 档案](https://www.polizei.sachsen.de/de/113164.htm)明确指向[Polizeidirektion Dresden 的 Medienservice 档案](https://medienservice.sachsen.de/medien/?search%5Binstitution_ids%5D%5B%5D=10997)。核验时 Medienservice 的 robots.txt 返回 404，无法取得可验证规则，因此没有自动抓取。其公告可能把 Dresden、Meißen、Sächsische Schweiz-Osterzgebirge 多个事件合并成一篇；不能把整篇公告当作一个市内案发点。

德累斯顿模块目前只能将**事先人工取得并放在本机的官方原文**以 JSONL 形式离线暂存：每行必须有 `source_id`、`source_url`、`publisher`、`title`、`published`、`body`。暂存过程不联网，写入 `source_verified=0` 和 `review_status=pending`；字段校验不等于核验原文。

若来自 [Medienservice Sachsen 注册投递](https://www.medienservice.sachsen.de/medien/account/new/other)、用户保存的页面/PDF/邮件或官方人工导出，JSONL 行还可带相对路径 `source_file` 和原文件字节的 `source_file_sha256`。支持 HTML、EML、PDF、完整 RSS/Atom XML；HTML、邮件、RSS 的所填正文必须在原文件文字中，摘要不算完整公告。PDF 只校验签名与哈希，转写须在逐篇复核时与原 PDF 核对。保存文件改变会记录新修订并清除旧复核状态。账号凭据和所有原件仍只在本机 Git 忽略目录。

```sh
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.dresden \
  --db .runtime/safety/cities/dresden/police.sqlite \
  --export-review .runtime/safety/cities/dresden/review-input.ndjson --max-records 100
```

此只读逐篇输入重新核对正文、修订、市域范围和原文件哈希，仍保留 `source_verified=false`、`publication_ready=false`。后续批次可用 `--review-offset` 分页并写不同的本地输出文件。它供 Codex 对照整篇原文拆案和场景，不能证明历史通报完整或自动进入地图。

## 纽伦堡来源与边界

[巴伐利亚警方原生公告](https://www.polizei.bayern.de/aktuelles/pressemitteilungen/)受其 [robots.txt](https://www.polizei.bayern.de/robots.txt) 的 `Disallow: /` 阻挡，本仓库不请求原生站的索引或文章。[Presseportal 上由 Polizeipräsidium Mittelfranken 署名的新闻室](https://www.presseportal.de/blaulicht/nr/6013)提供另一条有界本地采集路径。2026-09-28 核验时，[Presseportal robots.txt](https://www.presseportal.de/robots.txt) 允许该新闻室及文章路径；程序每次运行重新核验规则，规则缺失、请求被禁止或发布者不符时停止接收相应内容。请求间隔至少一秒，并遵守 robots 的更慢限制；单次最多续扫 10 页、检查 30 篇正文，失败重试有上限。年度游标和原文存于本机 `.runtime/safety/cities/nuremberg/newsroom.sqlite`，保存新闻室 ID、规范 URL、正文 SHA-256、修订历史与待审状态。旧的巴伐利亚原生页面人工暂存仍单独保存在 `police.sqlite`，不与新闻室表混写。

这个新闻室覆盖整个 Mittelfranken，包括 Fürth、Erlangen、Ansbach 等市镇及跨市高速。`nuremberg_candidate` 仅在正文有明确市域线索且没有已知混合辖区/区域道路提示时作为**复核候选**；新闻室标题、`Nürnberg (ots)` 发稿地及警局地址均不证明案发地。一次公告可能包含多地、多案或非案件内容，必须逐篇核查。

新闻室页码走到较早年份，只能说明本地已扫描到该新闻室的一个断点。新闻室与受阻的原生档案是否一致、历史公告是否齐全尚未核实，所以 `archive_complete` 和 `publication_ready` 对纽伦堡始终为 `false`。警方公告本身也不是全量犯罪记录。来源核验、逐篇 Codex 审查、所有者质询与批准之前，不发布记录或地图。

## 四城只读来源契约

`registry.py` 固定四个城市的 slug、显示名、EPSG、来源类型、来源 URL、采集模式和市域复核标记。Essen、Hannover、Nuremberg 使用 EPSG:25832；Dresden 使用 EPSG:25833。这些坐标系只是后续 GIS 的元数据，本仓库不生成坐标。

`source_audit.py` 以 SQLite 只读模式审计本地数据库，按年度输出版本号为 `1` 的 JSON。它适配 Essen、Hannover、Nuremberg 的在线采集表，以及 Dresden 和 Nuremberg 原生站的离线暂存表。纽伦堡默认优先审计 `newsroom.sqlite`；若尚无在线库，则审计旧 `police.sqlite` 暂存。每城有 `archive_complete`、`source_verified`、`publication_ready`、`blocking_reasons`、`records` 和 `municipal_review_candidates`。每条记录只导出来源 ID、URL、日期、SHA-256、修订号、市域标记、复核状态及完整性布尔值；不导出标题、正文、市域证据原句、坐标或几何。审计时会在本机读取正文，重算哈希、核对修订表和市域标记，但不修改来源库。

`municipal_review_candidates` 只收录正文存在、哈希与修订一致、来源 ID/URL 合法、原文支持当前市域标记，且未被审查驳回的在线来源记录。这些记录仍是**待逐篇审查的市域线索**，不能据此推断具体案发点。离线暂存缺少可核查的原始来源核验记录，因此即使 SQLite 的可变 `source_verified` 字段被改为 `1`，审计输出仍将其判为未核验，不列入候选。在线记录的 `source_verified` 仅表示本地已保存文章的来源格式和正文完整性核对通过，不能代替对当前官网原文的再次复核。

现阶段 `publication_ready` 恒为 `false`。未完成的年度档案覆盖、未核验来源、缺少与修订绑定的 Codex 审查、缺少本批次所有者批准以及不存在获准地图构建，都会在 `blocking_reasons` 中说明。第一组工程消费此契约时仍须执行自己的逐篇审核与发布门禁。

## 本地运行

需要 Python 3.12 和 `uv`。

```sh
uv sync --locked
uv run ruff check .
uv run pytest -q
# 有界的原生来源试跑：最多 1 页索引、1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.essen --year 2026 --max-pages 1 --limit 1
# 汉诺威新闻室：单次续扫最多 1 页、下载最多 1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.hannover --year 2026 --pages 1 --limit 1
# 纽伦堡警方署名新闻室：单次续扫最多 1 页、下载最多 1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.nuremberg --year 2026 --pages 1 --limit 1
# 仅当人工已有原生站官方原文 JSONL 时，才运行离线暂存：
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.dresden --input .runtime/safety/cities/dresden/source.jsonl
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.nuremberg --input .runtime/safety/cities/nuremberg/source.jsonl
# 四城来源元数据审计；输出只有 JSON，不改变来源数据库
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.source_audit --year 2026
```

纽伦堡在线库使用 `.runtime/safety/cities/nuremberg/newsroom.sqlite`；其他默认库及纽伦堡原生站离线暂存使用 `.runtime/safety/cities/<slug>/police.sqlite`。埃森 `--full`、汉诺威和纽伦堡新闻室年度续扫会在多次运行间记录页码；`--max-pages`、`--pages`、`--limit` 只限制**一次网络采集运行**的请求量，并非审核篇数或发布时间表。纽伦堡游标续扫时还会刷新新闻室首页，所以实际索引请求最多多一页。来源失效时保持上次已保存的原文和修订，不生成替代数据。

`.runtime/`、原始公告、SQLite、下载缓存、生成城市数据、个人凭据均不进入 Git。CI 只运行合成测试，不向警方网站发请求。任何获准的公共数据版本应先完成来源审查、质量检查和所有者批准，并遵循第一组仓库的发布流程。

代码沿用 Apache-2.0 许可，见 [LICENSE](LICENSE)。
