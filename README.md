# 线束试验室本地导通复核

接纳员依据试验工单登记工装和应测支路，并接纳台式电导仪的原测。质控员选定冻结修订，在已知夹持电位下计算本地供流和耗散。次班按报告号领取原结论及原测出处，可将复测前后的两份报告用于复检。

## 运行

要求 Python 3.11，仅使用标准库。请在项目根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
python3 -B coupled_sample.py
python3 -B -m lab shift.sqlite3
```

演示读取 `examples/day_shift.json`，在临时库中登记和接纳，冻结、签发、勘误后再次签发并关闭连接。重开后验证两份报告并打印实际通流、耗散和出处。初始化保留已有工装、测量、冻结和报告，可在现有工作库上重复运行。跨工装复核见 `CROSS_FIXTURE.md`。

## Python 入口

使用 `lab.connect(path)` 打开 SQLite 连接，用 `lab.initialize(db)` 初始化。调用方负责关闭连接。写入口拥有各自的事务，调用时连接须处于事务之外。示例中的整数编号由工作库分配。

```python
from contextlib import closing

from lab import connect, initialize
from fixture.catalog import register
from intake.imports import ingest
from revision.amend import amend
from revision.freeze import freeze
from report.issue import issue
from report.read import read
from report.export import export

with closing(connect(':memory:')) as db:
    initialize(db)
    bench = register(db, 'T-14', '台架甲', ['a', 'b'], ['a', 'b'],
                     [('lead', 'a', 'b')])
    batch = ingest(db, bench, 'submit-14', '仪表 M1', [('lead', '500', 'mS')])
    first = freeze(db, batch.revision_id)
    clamps = [('a', 1), ('b', 0)]
    report = issue(db, first, clamps)
    corrected = amend(db, bench, batch.revision_id, '复测 M2', [('lead', 1, 'S')])
    second = issue(db, freeze(db, corrected), clamps)
    assert read(db, report.report_id).body['total_dissipation'] == batch_power()
    payload = export(db, second.report_id)
```

在上例的核对中使用 `Fraction(1, 2)` 作为原报告的手算耗散，修订后的耗散为 `Fraction(1)`。

- `register` 返回工装号。`FixtureStore(db).load_bench(bench_id)` 返回试验、工装名、有序拓扑和端子登记。工装名在试验内唯一。并接支路按不同名字分别登记。端子从已登记节点中选取，工装在登记后保持固定。
- `ingest` 返回 `Submission`，其中 `batch_id`、`revision_id` 和 `reading_refs` 记录首次接纳的批次、初始修订和 `(支路名, 读数引用)` 序列。`IntakeStore(db).load_readings(refs)` 按引用恢复原值、原单位、仪表出处及标准电导。原测可部分提交，冻结时核齐。一个新提交建立一条独立的勘误链。
- `amend` 返回新的修订号。替换清单至少有一条具名读数，必须使用该批次当前父修订。未改动的支路继续使用同一引用。`freeze` 返回指定修订的冻结号，完整的历史修订也可冻结。`RevisionStore(db).load_frozen(freeze_id)` 返回该处采用的有序支路读数。
- `issue` 与 `read` 返回 `LocalReport`，可访问 `report_id`、`body`、`receipt`。正文含试验、工装、确切修订和冻结号，以及 `clamps`、`potentials`、`supplies`、`branches`、`total_dissipation` 与 `source_power`。每条支路结果含登记端点、精确电导、电流、耗散、读数引用及原测出处。回执绑定报告、冻结和正文 SHA-256。`export` 返回已保存的正文 UTF-8 JSON 字节。JSON 的计算值为约分的 `分子/分母` 字符串，原值保留输入的整数或文本表示。

电导接受 `S` 和 `mS`。数值输入为精确整数或 Python 3.11 `Fraction` 可解析的有理数文本，布尔值和浮点数拒绝。夹持电位可为负。缺测无法冻结，已测零保留出处和零通流记录。每个正电导分量都须有至少一个夹持端子，包括孤立节点。一个分量内未夹持节点净流为零，支路按首端至末端计流，夹具向工装供流为正。节点和支路沿登记序，夹持和供流沿请求序。计算量分别以 S、V、A、W 表示。

非法登记、测量或夹持、同号重投冲突、异工装或陈旧父修订及缺测冻结报 `ValueError`。`freeze` 查询未知修订、`read` 和 `export` 查询未知报告报 `KeyError`。`issue` 对不可用的冻结号报 `ValueError`。SQLite 写入或提交失败时传播原异常并回滚，提交成功后返回可领取的报告。
